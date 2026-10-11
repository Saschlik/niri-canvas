PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
DATADIR ?= $(PREFIX)/share
APPDIR ?= $(DATADIR)/applications
ICONDIR ?= $(DATADIR)/icons/hicolor/scalable/apps
ICONPNGDIR ?= $(DATADIR)/icons/hicolor/256x256/apps
LIBDIR ?= $(PREFIX)/lib/niri-canvas

.PHONY: all install uninstall test

all:
	@echo "Niri Canvas — Ready to install. Run 'make install' (or 'sudo make install')."

install:
	mkdir -p $(DESTDIR)$(LIBDIR)
	cp -r src/niri_canvas $(DESTDIR)$(LIBDIR)/
	install -Dm755 bin/niri-canvas $(DESTDIR)$(BINDIR)/niri-canvas
	install -Dm755 bin/niri-canvas-cli $(DESTDIR)$(BINDIR)/niri-canvas-cli
	install -Dm644 ui/com.github.saschlik.NiriCanvas.desktop $(DESTDIR)$(APPDIR)/com.github.saschlik.NiriCanvas.desktop
	mkdir -p $(DESTDIR)$(ICONDIR)
	install -Dm644 assets/com.github.saschlik.NiriCanvas.svg $(DESTDIR)$(ICONDIR)/com.github.saschlik.NiriCanvas.svg
	mkdir -p $(DESTDIR)$(ICONPNGDIR)
	install -Dm644 assets/com.github.saschlik.NiriCanvas.png $(DESTDIR)$(ICONPNGDIR)/com.github.saschlik.NiriCanvas.png

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/niri-canvas
	rm -f $(DESTDIR)$(BINDIR)/niri-canvas-cli
	rm -f $(DESTDIR)$(APPDIR)/com.github.saschlik.NiriCanvas.desktop
	rm -f $(DESTDIR)$(ICONDIR)/com.github.saschlik.NiriCanvas.svg
	rm -f $(DESTDIR)$(ICONPNGDIR)/com.github.saschlik.NiriCanvas.png
	rm -rf $(DESTDIR)$(LIBDIR)

test:
	./bin/niri-canvas status
