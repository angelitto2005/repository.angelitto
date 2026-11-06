@echo off
setlocal
set ROOT=%~dp0
set ROOT=%ROOT:~0,-1%
set PATH=%ROOT%\toolchain\mingw64\bin;%PATH%
"%ROOT%\toolchain\cmake-4.4.5-windows-x86_64\bin\cmake.exe" -S "%ROOT%" -B "%ROOT%\build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER="%ROOT%\toolchain\mingw64\bin\g++.exe" -DCMAKE_C_COMPILER="%ROOT%\toolchain\mingw64\bin\gcc.exe"
if errorlevel 1 exit /b 1
"%ROOT%\toolchain\cmake-4.4.5-windows-x86_64\bin\cmake.exe" --build "%ROOT%\build" --config Release
