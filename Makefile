.PHONY: help install uninstall deb clean tray logs status check

help:
	@echo "battery-manager — common targets"
	@echo ""
	@echo "  make install    Run ./install.sh (source install)"
	@echo "  make uninstall  Run ./uninstall.sh"
	@echo "  make deb        Build .deb into build/"
	@echo "  make clean      Remove build/, venv/, __pycache__/"
	@echo "  make tray       Launch tray manually for dev/testing"
	@echo "  make logs       Tail daemon journal logs"
	@echo "  make status     Show systemd service status"
	@echo "  make check      Quick syntax + autodetect smoke test"

install:
	./install.sh

uninstall:
	./uninstall.sh

deb:
	./packaging/build-deb.sh

clean:
	rm -rf build/ venv/ __pycache__/ */__pycache__/

tray:
	./venv/bin/python ./battery_tray.py

logs:
	journalctl -u battery-manager.service -f

status:
	systemctl status battery-manager.service

check:
	@python3 -m py_compile battery_manager.py battery_tray.py && echo "python: ok"
	@bash -n install.sh uninstall.sh packaging/build-deb.sh && echo "shell: ok"
	@python3 -c "import sys; sys.path.insert(0,'.'); import battery_manager as bm; print('detected battery:', bm.detect_battery())"
