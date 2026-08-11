// The whole extension: one D-Bus method answering global.get_pointer().
//
// The compositor always knows where the pointer is. XWayland only knows
// while the pointer is over one of its own windows, which is why a gesture
// drawn over a Wayland-native window is never seen. This exports the
// compositor's answer on the shell's own bus name, so nothing new is owned
// and nothing is watched -- it is asked, and it replies.
import Gio from 'gi://Gio';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.ClaudePetPointer">
    <method name="GetPointer">
      <arg type="i" direction="out" name="x"/>
      <arg type="i" direction="out" name="y"/>
    </method>
  </interface>
</node>`;

export default class ClaudePetPointer extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/ClaudePetPointer');
    }

    disable() {
        this._dbus?.flush();
        this._dbus?.unexport();
        this._dbus = null;
    }

    GetPointer() {
        const [x, y] = global.get_pointer();
        return [x, y];
    }
}
