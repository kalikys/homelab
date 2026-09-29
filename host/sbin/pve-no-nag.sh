#!/bin/sh
F=/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
[ -f "$F" ] || exit 0
grep -q "void({ //Ext.Msg.show" "$F" && exit 0
sed -Ezi "s/(Ext\.Msg\.show\(\{\s+title: gettext\('No valid sub)/void({ \/\/\1/g" "$F"
