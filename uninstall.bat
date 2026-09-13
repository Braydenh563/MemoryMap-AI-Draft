@echo off
title MemoryMap AI - Uninstall
REM ===================================================================
REM  MemoryMap AI - uninstaller for Windows
REM
REM  Removes the virtual environment (.venv) that start.bat built, plus
REM  the caches that came with it, so the app stops being runnable from
REM  this folder. Your notes live in a separate data directory and are
REM  NEVER touched unless you explicitly pass --delete-data.
REM
REM  Flags: see "uninstall.bat --help". uninstall.sh takes the same set
REM  in the same order, the same way start.sh and start.bat do.
REM
REM  This script does not delete the project folder itself (the source
REM  code and this script). Delete the folder by hand afterwards if you
REM  want it gone completely - re-running start.bat at any point
REM  rebuilds .venv and picks up right where you left off, notes
REM  included.
REM
REM  The same cmd rules start.bat's header records apply here: no ( or )
REM  inside an ECHO within an IF block, %1 in a block is expanded at
REM  parse time, and a delayed-expansion ECHO puts its redirect first.
REM  The listing below is written as a chain of labels rather than nested
REM  IF blocks for exactly that reason - the rows carry paths.
REM ===================================================================

setlocal enabledelayedexpansion
for /F %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
cd /d "%~dp0"

REM --- Where the data actually is --------------------------------------
REM  The same precedence start.bat uses: this script has to be able to
REM  name, measure and (only if asked) delete the right folder on a
REM  machine where MEMORYMAP_DATA_DIR moved the notebook elsewhere.
set "DATA_DIR=%MEMORYMAP_DATA_DIR%"
if not defined DATA_DIR if exist ".env" (
  for /f "tokens=1,* delims==" %%K in ('findstr /B /C:"MEMORYMAP_DATA_DIR=" ".env" 2^>nul') do set "DATA_DIR=%%L"
)
if not defined DATA_DIR set "DATA_DIR=data"
set DATA_DIR=!DATA_DIR:"=!

set "MM_PORT=%MEMORYMAP_PORT%"
if not defined MM_PORT set "MM_PORT=8000"

REM --- Flags -----------------------------------------------------------
set "DRY_RUN=0"
set "DELETE_DATA=0"
set "SHORTCUTS=0"
set "ASSUME_YES=0"
set "EXPORT_TO="
set "EXPORT_GIVEN="
set "BAD_FLAG="

:parse_args
if "%~1"=="" goto :parse_done
if /i "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
  goto :parse_args
)
if /i "%~1"=="-n" (
  set "DRY_RUN=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--export" (
  REM  %~2 read before either SHIFT: see the header note. EXPORT_GIVEN
  REM  separates "no --export" from "--export with nothing after it": the
  REM  second used to fall through as the first, so the uninstall carried
  REM  on and removed .venv while the export nobody noticed was skipped.
  set "EXPORT_TO=%~2"
  set "EXPORT_GIVEN=1"
  shift
  shift
  goto :parse_args
)
if /i "%~1"=="--delete-data" (
  set "DELETE_DATA=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--shortcuts" (
  set "SHORTCUTS=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--yes" (
  set "ASSUME_YES=1"
  shift
  goto :parse_args
)
if /i "%~1"=="-y" (
  set "ASSUME_YES=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--help" goto :help
if /i "%~1"=="-h" goto :help
set "BAD_FLAG=%~1"
shift
goto :parse_args
:parse_done

REM  Exit 2 for a typo, the same code start.bat uses, so a wrapper script
REM  can tell "you typed it wrong" apart from "the uninstall failed".
if defined BAD_FLAG (
  echo Unknown option: !BAD_FLAG!
  echo.
  call :print_help
  endlocal
  exit /b 2
)

REM  A path that is missing, or that is the next flag rather than a path,
REM  is the same mistake and gets the same answer as start.bat gives a bad
REM  --port: exit 2 with the help, before anything is removed.
if not defined EXPORT_GIVEN goto :export_ok
if not defined EXPORT_TO goto :export_missing
if "!EXPORT_TO:~0,1!"=="-" goto :export_missing
goto :export_ok
:export_missing
echo --export needs a path, for example: uninstall.bat --export %USERPROFILE%\my-notes.zip
echo.
call :print_help
endlocal
exit /b 2
:export_ok

echo !ESC![1;38;5;73mMemoryMap AI - uninstall!ESC![0m
echo.

REM --- Is the app running? ----------------------------------------------
REM  Deleting .venv out from under a live server leaves a process with no
REM  interpreter files, a half-working app, and a support message that
REM  makes no sense. Only "busy with us" stops this script; a stranger on
REM  the port is none of an uninstaller's business.
call :port_check
if not defined MM_PORT_MINE goto :not_running
echo  !ESC![1;31m[x]!ESC![0m MemoryMap is still running on port !MM_PORT!.
echo         Close the app window, or press Ctrl+C in the window running it,
echo         then run this again. Nothing was changed.
pause
endlocal
exit /b 1
:not_running

REM --- What would go ----------------------------------------------------
REM  One list, printed by both the dry run and the real run, so the two
REM  can never disagree about what is about to happen. Sizes come from the
REM  venv Python while it still exists: cmd's own answer is DIR's English
REM  footer, and a wrong number is worse than no number.
set "VENV_MB=0"
set "CACHE_MB=0"
set "DATA_MB=0"
if exist ".venv\Scripts\python.exe" call :dir_mb ".venv" VENV_MB
if exist ".venv\Scripts\python.exe" call :dir_mb "!DATA_DIR!" DATA_MB
REM  FOR /D /R with a literal name yields <dir>\__pycache__ for every
REM  directory in the tree whether or not it exists, so the IF EXIST is
REM  what makes this a count of real folders rather than of directories.
set "PYCACHE_COUNT=0"
for /d /r %%D in (__pycache__) do if exist "%%D" call :count_pycache

echo  Would remove:
if exist ".venv" (
  call :line ".venv" "!VENV_MB! MB"
) else (
  call :line ".venv" "not present"
)
if exist ".pytest_cache" call :line ".pytest_cache" "cache"
if exist ".ruff_cache" call :line ".ruff_cache" "cache"
if not "!PYCACHE_COUNT!"=="0" call :line "__pycache__ folders" "!PYCACHE_COUNT! under this folder"
if "!SHORTCUTS!"=="1" call :list_shortcut
if "!DELETE_DATA!"=="1" goto :list_data
echo.
echo  !ESC![1;38;5;73m[kept]!ESC![0m Your notes in !DATA_DIR!, !DATA_MB! MB. Pass --delete-data to remove them.
echo  !ESC![1;38;5;73m[kept]!ESC![0m .env, so a reinstall finds your settings again.
goto :listed
:list_data
call :line "!DATA_DIR!" "!DATA_MB! MB - your notes"
call :line ".env" "settings"
:listed

echo.
set /a FREES_MB=VENV_MB
echo  That frees about !FREES_MB! MB.

if not "!DRY_RUN!"=="1" goto :not_dry
echo.
echo  !ESC![1;38;5;73m[dry run]!ESC![0m Nothing was changed. Run without --dry-run to do it.
endlocal
exit /b 0
:not_dry

REM --- Export first -----------------------------------------------------
REM  Before anything is removed, because an export that runs after .venv
REM  is gone has no interpreter to run in.
if not defined EXPORT_TO goto :no_export
echo.
if exist ".venv\Scripts\python.exe" goto :do_export
echo  !ESC![1;31m[x]!ESC![0m Cannot export: .venv is already gone, so there is no Python to run.
echo         Run start.bat once to rebuild it, export, then uninstall.
pause
endlocal
exit /b 1
:do_export
echo  !ESC![1;38;5;73m[..]!ESC![0m Exporting your notes to !EXPORT_TO!...
".venv\Scripts\python.exe" -m memorymap --export "!EXPORT_TO!"
if not errorlevel 1 goto :no_export
echo  !ESC![1;31m[x]!ESC![0m The export failed, so nothing was removed.
pause
endlocal
exit /b 1
:no_export

REM  A double-click, or a stray extra click meaning to hit start.bat,
REM  shouldn't be able to reach the actual removal steps below without a
REM  clear, explicit "yes" first - asked for directly. This is separate
REM  from, and in addition to, the per-step confirmation further down.
if "!ASSUME_YES!"=="1" goto :confirmed
echo.
set /p "REPLY=Continue? [y/N] "
if /i "!REPLY!"=="y" goto :confirmed
echo Cancelled - nothing was changed.
pause
endlocal
exit /b 0
:confirmed
echo.

REM --- 1. Remove the virtual environment and its caches -----------------
if not exist ".venv" goto :no_venv
set "DOIT=!ASSUME_YES!"
if "!DOIT!"=="1" goto :remove_venv
set /p "REPLY=Remove the .venv folder, all installed dependencies? [y/N] "
if /i "!REPLY!"=="y" set "DOIT=1"
if "!DOIT!"=="1" goto :remove_venv
echo  !ESC![1;33m[skipped]!ESC![0m .venv left in place.
set "VENV_MB=0"
goto :caches
:remove_venv
rmdir /s /q ".venv"
echo  !ESC![1;38;5;73m[done]!ESC![0m Removed .venv.
goto :caches
:no_venv
echo  !ESC![1;38;5;73m[skip]!ESC![0m No .venv found - nothing to remove there.
set "VENV_MB=0"

:caches
if exist ".pytest_cache" rmdir /s /q ".pytest_cache" >nul 2>nul
if exist ".ruff_cache" rmdir /s /q ".ruff_cache" >nul 2>nul
for /d /r %%D in (__pycache__) do if exist "%%D" rmdir /s /q "%%D" >nul 2>nul
echo  !ESC![1;38;5;73m[done]!ESC![0m Removed the build caches.

REM --- 2. The shortcut --------------------------------------------------
if not "!SHORTCUTS!"=="1" goto :notes
set "MM_LNK=%USERPROFILE%\Desktop\MemoryMap AI.lnk"
if not exist "!MM_LNK!" goto :no_shortcut
del /q "!MM_LNK!" >nul 2>nul
echo  !ESC![1;38;5;73m[done]!ESC![0m Removed !MM_LNK!
goto :notes
:no_shortcut
echo  !ESC![1;38;5;73m[skip]!ESC![0m No shortcut found to remove.

REM --- 3. Your notes: opt-in only, asked again even with --yes unless -----
REM        --delete-data was passed explicitly. A stray "uninstall" is not
REM        consent to lose a notebook.
:notes
if not "!DELETE_DATA!"=="1" goto :finished
if not exist "!DATA_DIR!" goto :no_data
echo.
echo  !ESC![1;31mThis deletes your notes, documents, images and settings in:!ESC![0m
for %%D in ("!DATA_DIR!") do echo    %%~fD
set /p "REPLY=Type DELETE to confirm: "
if not "!REPLY!"=="DELETE" goto :data_kept
rmdir /s /q "!DATA_DIR!"
REM  .env goes with the notes and not before them: it carries the path to
REM  the notebook and the settings that reach it, so removing it while the
REM  notes survive is how someone loses track of where their own notes are.
if exist ".env" del /q ".env" >nul 2>nul
echo  !ESC![1;38;5;73m[done]!ESC![0m Deleted !DATA_DIR! and .env.
goto :finished
:data_kept
echo  !ESC![1;33m[skipped]!ESC![0m Data left in place - the confirmation text did not match.
goto :finished
:no_data
echo  !ESC![1;38;5;73m[skip]!ESC![0m No data directory found at !DATA_DIR!.

:finished
REM --- Sizes after ------------------------------------------------------
REM  Only what actually went is counted: someone who answered no at the
REM  .venv prompt has not freed anything, and a figure that says otherwise
REM  is worse than none.
set /a FREED_MB=0
if not exist ".venv" set /a FREED_MB=VENV_MB
echo.
echo  !ESC![1;38;5;73mFreed:!ESC![0m !FREED_MB! MB
if "!DELETE_DATA!"=="1" goto :no_kept_line
if "!DATA_MB!"=="0" goto :no_kept_line
echo  !ESC![1;38;5;73mKept:!ESC![0m  !DATA_MB! MB of notes in !DATA_DIR!
:no_kept_line
echo.
echo  Uninstall finished. This folder's source code is still here -
echo  delete it by hand if you want it fully gone, or run start.bat
echo  any time to reinstall and pick up right where you left off.
pause
endlocal
goto :eof

REM ====================================================================
REM  Subroutines
REM ====================================================================

:help
call :print_help
endlocal
exit /b 0

:print_help
echo MemoryMap AI uninstaller
echo.
echo Usage: uninstall.bat [options]
echo.
echo   --dry-run       List what would be removed, with sizes, and change nothing
echo   --export PATH   Write your notes to PATH as a Markdown zip first
echo   --delete-data   Also delete your notes and .env, asks separately
echo   --shortcuts     Also remove the desktop shortcut start.bat --shortcut made
echo   --yes           Skip the "remove .venv?" prompts
echo   --help          Show this message and exit
echo.
echo Your notes are never deleted unless you pass --delete-data AND then type
echo DELETE at its own confirmation prompt - --yes does not skip that one.
echo.
echo Your notes: !DATA_DIR!
echo.
echo This does not delete the project folder itself. Re-run start.bat any
echo time afterwards to reinstall and pick up right where you left off.
exit /b 0

REM  One listing row, one column width, set by a padded variable because
REM  cmd has no printf and a hand-counted column goes ragged the first
REM  time a path is long.
:line
set "MM_L_LABEL=%~1                            "
set "MM_L_LABEL=!MM_L_LABEL:~0,28!"
set "MM_L_VALUE=%~2"
echo(   !MM_L_LABEL! !MM_L_VALUE!
exit /b 0

:count_pycache
set /a PYCACHE_COUNT+=1
exit /b 0

REM  A directory's size in whole megabytes, asked of the venv Python:
REM  cmd's only answer is DIR's English "bytes free" footer.
:dir_mb
set "MM_MB=0"
for /f "usebackq delims=" %%S in (`".venv\Scripts\python.exe" -c "import os,sys;p=sys.argv[1];t=sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(p) for f in fs) if os.path.isdir(p) else 0;print(t//1048576)" "%~1" 2^>nul`) do set "MM_MB=%%S"
set "%~2=!MM_MB!"
exit /b 0

REM  Exactly the path start.bat --shortcut writes, and nothing else: an
REM  uninstaller that guesses at desktop files is one that deletes somebody
REM  else's launcher.
:list_shortcut
set "MM_LNK=%USERPROFILE%\Desktop\MemoryMap AI.lnk"
if exist "!MM_LNK!" call :line "shortcut" "!MM_LNK!"
if not exist "!MM_LNK!" call :line "shortcut" "none found"
exit /b 0

REM  The same two questions start.bat asks: is the port busy, and is it
REM  busy with us. netstat rather than a socket, because cmd has no
REM  equivalent of bash's /dev/tcp.
:port_check
set "MM_PORT_BUSY="
set "MM_PORT_MINE="
where netstat >nul 2>nul
if errorlevel 1 exit /b 0
for /f "delims=" %%L in ('netstat -an -p TCP 2^>nul ^| findstr /C:":!MM_PORT! " ^| findstr /I /C:"LISTENING"') do set "MM_PORT_BUSY=1"
if not defined MM_PORT_BUSY exit /b 0
where curl >nul 2>nul
if errorlevel 1 exit /b 0
for /f "delims=" %%H in ('curl -fsS --max-time 3 "http://127.0.0.1:!MM_PORT!/health" 2^>nul ^| findstr /C:"MemoryMap AI"') do set "MM_PORT_MINE=1"
exit /b 0
