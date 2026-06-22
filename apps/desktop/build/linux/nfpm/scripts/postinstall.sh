#!/bin/sh

if command -v update-desktop-database >/dev/null 2>&1; then
  echo "Updating desktop database..."
  update-desktop-database -q /usr/share/applications
else
  echo "Warning: update-desktop-database command not found. Desktop file may not be immediately recognized." >&2
fi

if command -v update-mime-database >/dev/null 2>&1; then
  echo "Updating MIME database..."
  update-mime-database -n /usr/share/mime
else
  echo "Warning: update-mime-database command not found. Custom URL schemes may not be immediately recognized." >&2
fi

exit 0
