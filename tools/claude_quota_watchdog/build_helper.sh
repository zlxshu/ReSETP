#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
app_dir="${script_dir}/ReSETP Claude Quota Watchdog Helper.app"
contents_dir="${app_dir}/Contents"
macos_dir="${contents_dir}/MacOS"
executable="${macos_dir}/ReSETPClaudeWakeHelper"

mkdir -p "${macos_dir}"
/usr/bin/clang \
  -fobjc-arc \
  -O \
  -framework AppKit \
  -framework ApplicationServices \
  -framework Foundation \
  "${script_dir}/ClaudeWakeHelper.m" \
  -o "${executable}"
/usr/bin/env COPYFILE_DISABLE=1 /bin/cp \
  "${script_dir}/HelperInfo.plist" \
  "${contents_dir}/Info.plist"
/usr/bin/find "${app_dir}" -type f -name '._*' -delete
/usr/bin/codesign --force --deep --sign - "${app_dir}"
/usr/bin/find "${app_dir}" -type f -name '._*' -delete
echo "${app_dir}"
