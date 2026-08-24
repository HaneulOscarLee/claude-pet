// The same one method, in the pre-45 extension format.
//
// GNOME 45 moved extensions to ES modules and a class extending Extension;
// before that they are plain scripts using `imports.*` and exporting an
// `init()` that returns an object with enable/disable. A 45+ extension does
// not load at all on GNOME 42 -- Ubuntu 22.04's version -- and the shell says
// nothing about why, which is exactly how "the pet cannot see my pointer over
// the browser" looked on that machine.
const { Gio } = imports.gi;

const IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.ClaudePetPointer">
    <method name="GetPointer">
      <arg type="i" direction="out" name="x"/>
      <arg type="i" direction="out" name="y"/>
    </method>
  </interface>
</node>`;

class ClaudePetPointer {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/ClaudePetPointer');
    }

    disable() {
        if (this._dbus) {
            this._dbus.flush();
            this._dbus.unexport();
            this._dbus = null;
        }
    }

    GetPointer() {
        const [x, y] = global.get_pointer();
        return [x, y];
    }
}

function init() {
    return new ClaudePetPointer();
}
