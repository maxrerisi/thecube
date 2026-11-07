#!/bin/sh
# Renders logo.png: logo_fork.svg (code-drawn pitchfork on Duke blue) + "W" and "U" in Garamond Bold.
cd "$(dirname "$0")"
FONT="${FONT:-$HOME/Library/Fonts/AGaramondPro-Bold.otf}"  # Adobe Garamond Pro Bold
magick -background none logo_fork.svg \
  -font "$FONT" -fill white -pointsize 400 -gravity center \
  -annotate -190-165 W -annotate +235+195 U logo.png
