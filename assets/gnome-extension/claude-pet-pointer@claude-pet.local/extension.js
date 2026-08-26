// Two D-Bus methods on the shell's own bus name: where the pointer is, and
// raise a window given the pids that might own it.
//
// Both exist because an *external* client cannot do them on a Wayland session
// -- XWayland only knows the pointer over its own windows, and a client may
// not raise another application's window at all. The compositor can do both,
// so this asks it. Nothing is watched and no bus name of its own is owned.
import Gio from 'gi://Gio';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

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

    // Raise the most-recently-focused window owned by one of `pids`. The
    // compositor is allowed to activate any window, so this works for a
    // native Wayland terminal that no external tool could raise -- and needs
    // no XWayland wrapping of the terminal, which is what froze it when an
    // X11 window (rviz) came and went.
    RaiseWindowForPids(pids) {
        const wanted = new Set(pids);
        let best = null;
        for (const actor of global.get_window_actors()) {
            const w = actor.meta_window;
            if (!w || !wanted.has(w.get_pid())) continue;
            // Prefer the one used most recently, so several terminals from one
            // process land on the one you were last in.
            if (best === null || w.get_user_time() > best.get_user_time())
                best = w;
        }
        if (best === null) return false;
        best.get_workspace()?.activate_with_focus(best, global.get_current_time());
        best.activate(global.get_current_time());
        return true;
    }
}
