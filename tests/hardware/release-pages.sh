#!/bin/sh
printf 'Content-Type: application/json\r\n\r\n'
[ -z "$PATH_INFO" ] || exec cat "$DOCUMENT_ROOT/releases$PATH_INFO"
page=1
IFS='&'
for pair in $QUERY_STRING; do
  case $pair in page=*) page=${pair#page=} ;; esac
done
if [ -f "$DOCUMENT_ROOT/pages/$page.json" ]; then
  cat "$DOCUMENT_ROOT/pages/$page.json"
else
  echo '[]'
fi
