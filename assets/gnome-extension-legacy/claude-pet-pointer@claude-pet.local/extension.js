// The same two methods, in the pre-45 extension format (GNOME 42, Ubuntu 22.04).
const { Gio } = imports.gi;

const IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.ClaudePetPointer">
    <method name="GetPointer">
      <arg type="i" direction="out" name="x"/>
      <arg type="i" direction="out" name="y"/>
    </method>
    <method name="RaiseWindowForPids">
      <arg type="ai" direction="in" name="pids"/>
      <arg type="b" direction="out" name="raised"/>
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

    RaiseWindowForPids(pids) {
        const wanted = {};
        for (const p of pids) wanted[p] = true;
        let best = null;
        for (const actor of global.get_window_actors()) {
            const w = actor.meta_window;
            if (!w || !wanted[w.get_pid()]) continue;
            if (best === null || w.get_user_time() > best.get_user_time())
                best = w;
        }
        if (best === null) return false;
        const ws = best.get_workspace();
        if (ws) ws.activate_with_focus(best, global.get_current_time());
        best.activate(global.get_current_time());
        return true;
    }
}

function init() {
    return new ClaudePetPointer();
}
