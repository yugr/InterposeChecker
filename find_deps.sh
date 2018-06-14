#!/bin/sh

# The MIT License (MIT)
# 
# Copyright (c) 2018 Yury Gribov
# 
# Use of this source code is governed by The MIT License (MIT)
# that can be found in the LICENSE.txt file.

set -eu

error() {
  echo >&2 "$(basename $0): error: $@"
  exit 1
}

warn() {
  echo >&2 "$(basename $0): warning: $@"
}

print_help_and_exit() {
  cat <<EOF
Usage: $(basename $0) [OPT]... PKG [DEPTH]
Get package dependencies (forward or backward), up to a certain depth.

Options:
  -r, --reverse   Find forward deps (default is backward).
  -h, --help      Print help and exit.
  -k, --keep      Do not remove temp files.
  -x              Enable shell tracing.
EOF
  exit 1
}

ARGS=$(getopt -o 'rhkx' --long 'reverse,no-reverse,keep,no-keep,help' -n $(basename $0) -- "$@")
eval set -- "$ARGS"

rev=
keep=
while true; do
  case "$1" in
    -r | --reverse)
      rev=1
      shift
      ;;
    --no-reverse)
      rev=
      shift
      ;;
    -k | --keep)
      keep=1
      shift
      ;;
    --no-keep)
      keep=
      shift
      ;;
    -h | --help)
      print_help_and_exit
      ;;
    -x)
      set -x
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      error "unknown option: $1"
      ;;
    *)
      error 'internal error'
      ;;
  esac
done

if [ $# -eq 0 ]; then
  print_help_and_exit
elif test $# = 2; then
  pkg=$1
  depth=$2
elif test $# = 1; then
  pkg=$1
  depth=1000
else
  cat >&2 <<EOF
Usage: $(basename $0) [OPT]... PKG [DEPTH]
Run \`$(basename $0) --help' for more details.
EOF
  exit 1
fi

me=$(basename $0)

wd=$(mktemp -d --suffix=.$me.$$)
test -n "$keep" || trap "rm -rf $wd" EXIT

echo $pkg > $wd/pkgs.0
for i in `seq 1 $depth`; do
  sort -u $wd/pkgs.* > $wd/old

  for p in $(cat $wd/pkgs.$((i - 1))); do
    echo "$i: analyzing $p"

    if test -z "$rev"; then
      # $ apt-cache depends vlc
      # vlc
      #  PreDepends: dpkg
      #    dpkg:i386
      #  Depends: fonts-freefont-ttf
      #  Depends: vlc-nox
      #  Depends: libaa1
      # |Depends: libavcodec-ffmpeg56
      apt-cache depends $p | grep '^ *|\? *\(Pre\)\?Depends:' | tr -d '<>' | awk '{print $2}'
    else
      apt-cache rdepends $p | tail -n +3 | sed 's/^ *//'
    fi > $wd/new

    # Analyze only those packages which we haven't yet seen
    sort -u -o $wd/new $wd/new
    comm -23 $wd/new $wd/old > $wd/pkgs.$i.$p
  done

  ls $wd/pkgs.$i.* >/dev/null 2>&1 || break

  cat $wd/pkgs.$i.* | sort -u > $wd/pkgs.$i
  rm $wd/pkgs.$i.*
done

sort -u $wd/pkgs.* > $wd/pkgs
cat $wd/pkgs
echo "For a total of $(wc -l < $wd/pkgs) packages"
test -z "$keep" || echo "Temp files are in $wd"
