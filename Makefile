.PHONY: all exe installer clean stop

UNAME_S := $(shell uname -s 2>/dev/null)
WIN_LOCALAPPDATA := $(shell cmd.exe /C echo %LOCALAPPDATA% 2>/dev/null | tr -d '\r')
WIN_LOCALAPPDATA_WSL := $(shell wslpath '$(WIN_LOCALAPPDATA)' 2>/dev/null)

ifeq ($(UNAME_S),Linux)
PS ?= powershell.exe
PYTHON ?= $(WIN_LOCALAPPDATA_WSL)/Programs/Python/Python311/python.exe
ISCC ?= $(WIN_LOCALAPPDATA_WSL)/Programs/Inno Setup 6/ISCC.exe
RM_BUILD = rm -rf build dist/AutoKeyboard dist/AutoKeyboard.exe installer/AutoKeyboard_Setup.exe
STOP_APP = $(PS) -NoProfile -ExecutionPolicy Bypass -Command 'Get-Process AutoKeyboard -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like "*\dist\AutoKeyboard\AutoKeyboard.exe" -or $$_.Path -like "*\dist\AutoKeyboard.exe" } | Stop-Process -Force -ErrorAction SilentlyContinue; exit 0'
else
PS ?= powershell
PYTHON ?= python
ISCC ?= $(LOCALAPPDATA)\Programs\Inno Setup 6\ISCC.exe
RM_BUILD = powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -Recurse -Force build, dist\AutoKeyboard -ErrorAction SilentlyContinue; Remove-Item -Force dist\AutoKeyboard.exe, installer\AutoKeyboard_Setup.exe -ErrorAction SilentlyContinue"
STOP_APP = $(PS) -NoProfile -ExecutionPolicy Bypass -Command "Get-Process AutoKeyboard -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like '*\dist\AutoKeyboard\AutoKeyboard.exe' -or $$_.Path -like '*\dist\AutoKeyboard.exe' } | Stop-Process -Force -ErrorAction SilentlyContinue; exit 0"
endif

all: exe installer

stop:
	$(STOP_APP)

exe: stop
	"$(PYTHON)" -m PyInstaller AutoKeyboard.spec --clean --noconfirm

installer: exe
	"$(ISCC)" installer.iss

clean:
	$(RM_BUILD)
test:
	"$(PYTHON)" -m unittest discover -s tests
