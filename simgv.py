#!/usr/bin/env python3
import sys
import os
import gi

os.environ["GSK_RENDERER"] = "gl"

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Gsk', '4.0')
gi.require_version('Graphene', '1.0')
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
gi.require_version('Pango', '1.0')
gi.require_version('Gst', '1.0')

from gi.repository import Gtk, Gdk, Gsk, Graphene, Gio, GLib, Pango, Gst

class ImageViewer(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("SIMGV")
        self.set_default_size(900, 700)

        self.has_image = False
        self.zoom = 1.0
        self.base_offset_x = 0.0
        self.base_offset_y = 0.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.mouse_x = 0.0
        self.mouse_y = 0.0
        self.is_fitted = True

        self.setup_actions(app)
        self.setup_ui()
        self.setup_controllers()
        self.setup_css()

        GLib.timeout_add(500, self.update_time_label)

    def setup_ui(self):
        # main box containing the viewer and bottom bar
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(vbox)
                
        # scrolled viewport
        self.viewport = Gtk.ScrolledWindow()
        self.viewport.set_hexpand(True)
        self.viewport.set_vexpand(True)
        self.viewport.add_css_class("viewer-canvas")

        # reset view until user interacts
        hadj = self.viewport.get_hadjustment()
        vadj = self.viewport.get_vadjustment()
        
        hadj.connect("notify::page-size", self.on_vp_resize)
        vadj.connect("notify::page-size", self.on_vp_resize)

        self.fixed = Gtk.Fixed()
        self.fixed.add_css_class("viewer-canvas")
        self.viewport.set_overflow(Gtk.Overflow.HIDDEN)

        self.player = Gst.ElementFactory.make("playbin", "player")
        self.gtk_sink = Gst.ElementFactory.make("gtk4paintablesink", "gtk_sink")

        if not self.gtk_sink:
            print("WARNING: gtk4paintablesink not found")
            self.player = None
        else:
            self.player.set_property("video-sink", self.gtk_sink)
        
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(False)
        self.fixed.put(self.picture, 0, 0)

        self.viewport.set_child(self.fixed)
        vbox.append(self.viewport)
        
        # bottom bar with file name, image size, and zoom  %
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bottom_bar.add_css_class("bottom-bar")

        self.filename_label = Gtk.Label(label="No image loaded")
        self.filename_label.set_halign(Gtk.Align.START)
        self.filename_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.size_label = Gtk.Label(label="")
        self.resolution_label = Gtk.Label(label="")
        self.zoom_label = Gtk.Label(label="")
        self.time_label = Gtk.Label(label="")

        bottom_bar.append(self.filename_label)
        bottom_bar.append(self.size_label)
        bottom_bar.append(self.resolution_label)
        bottom_bar.append(self.zoom_label)
        bottom_bar.append(self.time_label)

        vbox.append(bottom_bar)

    def setup_controllers(self):
        # drag gesture
        self.drag_ctrl = Gtk.GestureDrag()
        self.drag_ctrl.connect("drag-update", self.on_drag_update)
        self.drag_ctrl.connect("drag-end", self.on_drag_end)
        self.viewport.add_controller(self.drag_ctrl)

        # scroll control
        self.scroll_ctrl = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        self.scroll_ctrl.connect("scroll", self.on_scroll)
        self.viewport.add_controller(self.scroll_ctrl)

        # read mouse pos for zooming towards mouse
        self.motion_ctrl = Gtk.EventControllerMotion()
        self.motion_ctrl.connect("motion", self.on_motion)
        self.viewport.add_controller(self.motion_ctrl)

        # double click for resetting view
        self.click_ctrl = Gtk.GestureClick()
        self.click_ctrl.connect("pressed", self.on_click_pressed)
        self.viewport.add_controller(self.click_ctrl)

        self.kb_ctrl = Gtk.EventControllerKey()
        self.kb_ctrl.connect("key-pressed", self.on_key_pressed)
        self.add_controller(self.kb_ctrl)

    def setup_css(self):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .viewer-canvas {
                background-color: #282828;
            }

            .bottom-bar {
                padding: 5px 10px 5px 10px;
                background-color: #282828;
                color: #ebdbb2;
            }

            srcollbar,
            scrollbar:hover,
            scrollbar.overlay_indicator,
            scrollbar.hovering,
            scrollbar trough,
            scrollbar:hover trough {
                background-color: transparent;
                border: none;
                background-image: none;
                box-shadow: none;
            }

            scrollbar slider {
                background-color: #ebdbb2;
                margin: 2px;
            }

            scrollbar slider:active {
                background-color: #458588;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def setup_actions(self, app):
        # primary+o for open
        open_action = Gio.SimpleAction.new("open", None)
        open_action.connect("activate", self.on_open_action)
        
        self.add_action(open_action)
        
        app.set_accels_for_action("win.open", ["<primary>o"])

        # q for quit
        close_action = Gio.SimpleAction.new("close", None)
        close_action.connect("activate", lambda action, param: self.close())

        self.add_action(close_action)

        app.set_accels_for_action("win.close", ["q"])

    def show_open_dialog(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("Open Image")

        image_filter = Gtk.FileFilter()
        image_filter.set_name("Images")

        image_filter.add_mime_type("image/*")
        image_filter.add_mime_type("video/*")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)

        dialog.set_filters(filters)
        dialog.set_default_filter(image_filter)

        dialog.open(self, None, self.on_file_chooser_response)

    def on_vp_resize(self, widget, param):
        if self.has_image and self.is_fitted:
            self.reset_view()

    def on_open_action(self, action, param):
        self.show_open_dialog()

    def on_file_chooser_response(self, dialog, response):
        try:
            file = dialog.open_finish(response)
            if file is not None:
                self.load_file(file.get_path())

        except GLib.Error as e:
            if e.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                pass
            else:
                print(f"Error opening file dialog: {e}")

    def reset_view(self):
        if not self.has_image:
            return False

        texture = self.picture.get_paintable()
        if not texture: 
            return False

        img_w = texture.get_intrinsic_width()
        img_h = texture.get_intrinsic_height()

        if img_w <= 0 or img_h <= 0:
            return True
        
        view_w = self.viewport.get_width()
        view_h = self.viewport.get_height()

        if view_w <= 0 or view_h <= 0:
            return True 
            
        scale_x = view_w / float(img_w)
        scale_y = view_h / float(img_h)
        self.zoom = min(scale_x, scale_y, 1.0) 
        
        self.base_offset_x = (view_w - (img_w * self.zoom)) / 2.0
        self.base_offset_y = (view_h - (img_h * self.zoom)) / 2.0
            
        self.offset_x = self.base_offset_x
        self.offset_y = self.base_offset_y

        self.is_fitted = True
        
        self.update_transform()
        
        return False

    def load_file(self, filepath):
        content_type, _ = Gio.content_type_guess(filepath, None)

        if content_type and content_type.startswith("video/") and self.player:
            self.load_video(filepath)
        else:
            self.load_image(filepath)
        
    def load_image(self, filepath):
        if self.player:
            self.player.set_state(Gst.State.NULL)
        
        file = Gio.File.new_for_path(filepath)
        try:
            texture = Gdk.Texture.new_from_file(file)
        except GLib.Error as e:
            print(f"Error loading image: {e}")
            return
            
        self.picture.set_paintable(texture)
        self.has_image = True

        self.filename_label.set_text(file.get_basename())
        
        img_w = texture.get_width()
        img_h = texture.get_height()

        self.resolution_label.set_text(f"{img_w}x{img_h}px")
        self.set_fsize_label(file)

        self.is_fitted = True
        self.reset_view()
        
    def load_video(self, filepath):
        self.player.set_state(Gst.State.NULL)
        file = Gio.File.new_for_path(filepath)
        self.player.set_property("uri", file.get_uri())
        
        # Start playback FIRST
        self.player.set_state(Gst.State.PLAYING)
        
        # THEN grab the paintable and give it to the picture widget
        paintable = self.gtk_sink.get_property("paintable")
        self.picture.set_paintable(paintable)
        
        self.has_image = True

        self.resolution_label.set_text("Video")
        self.filename_label.set_text(file.get_basename())
        self.set_fsize_label(file)
        
        self.is_fitted = True
        GLib.idle_add(self.reset_view)

    def set_fsize_label(self, file):
        # self.size_label.set_text(str(file.measure_disk_usage(Gio.FileMeasureFlags.NONE, None, None, None)[1]))
        fsize = file.measure_disk_usage(Gio.FileMeasureFlags.APPARENT_SIZE)[1]

        a = ['b', 'kb', 'mb', 'gb', 'tb', 'pb', 'eb']
        n = 0
        while fsize > 1024:
            fsize /= 1024
            n += 1
        self.size_label.set_text(f"{fsize:.2f}{a[n]}")

    def format_time(self, ns):
        if ns < 0:
            return "00:00"

        total_sec = ns // 1_000_000_000
        min = total_sec // 60
        sec = total_sec % 60

        return f"{min:02d}:{sec:02d}"

    def update_time_label(self):
        if not self.player or not self.has_image:
            self.time_label.set_text("")
            return True

        _, state, _ = self.player.get_state(0)
        if state in (Gst.State.PAUSED, Gst.State.PLAYING):
            has_pos, position = self.player.query_position(Gst.Format.TIME)
            has_dur, duration = self.player.query_duration(Gst.Format.TIME)

            if has_dur and has_pos:
                pos_str = self.format_time(position)
                dur_str = self.format_time(duration)
                self.time_label.set_text(f"{pos_str}/{dur_str}")
        else:
            self.time_label.set_text("")

        return True
        
    def update_transform(self):
        if not self.has_image: return
            
        point = Graphene.Point()
        point.x = self.offset_x
        point.y = self.offset_y
        
        transform = Gsk.Transform.new()
        transform = transform.translate(point)
        transform = transform.scale(self.zoom, self.zoom)
        
        self.fixed.set_child_transform(self.picture, transform)

        self.zoom_label.set_text(f"{int(self.zoom * 100)}%")

    def on_motion(self, controller, x, y):
        self.mouse_x = x
        self.mouse_y = y

    def on_drag_update(self, gesture, offset_x, offset_y):
        if not self.has_image: return

        self.is_fitted = False
        
        self.offset_x = self.base_offset_x + offset_x
        self.offset_y = self.base_offset_y + offset_y
        self.update_transform()

    def on_drag_end(self, gesture, offset_x, offset_y):
        if not self.has_image: return
        
        self.base_offset_x += offset_x
        self.base_offset_y += offset_y
        self.offset_x = self.base_offset_x
        self.offset_y = self.base_offset_y
        self.update_transform()

    def on_scroll(self, controller, dx, dy):
        if not self.has_image: return False

        self.is_fitted = False
        
        zoom_factor = 1.1 if dy < 0 else (1/1.1)
        new_zoom = self.zoom * zoom_factor
        
        if new_zoom < 0.05 or new_zoom > 50.0:
            return True
            
        self.zoom = new_zoom
        
        self.base_offset_x = self.mouse_x - ((self.mouse_x - self.base_offset_x) * zoom_factor)
        self.base_offset_y = self.mouse_y - ((self.mouse_y - self.base_offset_y) * zoom_factor)
        self.offset_x = self.base_offset_x
        self.offset_y = self.base_offset_y
        
        self.update_transform()
        return True

    def on_click_pressed(self, gesture, n_press, x, y):
        if n_press == 2:
            self.reset_view()

    def on_key_pressed(self, controller, keyval, keycode, state):
        if not self.has_image:
            return False

        pan_step = 50
        handled = False

        # move keybinds
        if keyval == Gdk.KEY_Left:
            self.base_offset_x += pan_step
            handled = True
        elif keyval == Gdk.KEY_Right:
            self.base_offset_x -= pan_step
            handled = True
        elif keyval == Gdk.KEY_Up:
            self.base_offset_y += pan_step
            handled = True
        elif keyval == Gdk.KEY_Down:
            self.base_offset_y -= pan_step
            handled = True

        # zoom keybinds
        elif keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_equal, Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            zoom_factor = 1.1 if keyval in (Gdk.KEY_plus, Gdk.KEY_KP_Add, Gdk.KEY_equal) else (1/1.1)
            new_zoom = self.zoom * zoom_factor

            if 0.05 <= new_zoom <= 50.0:
                self.zoom = new_zoom;

                view_w = self.viewport.get_width()
                view_h = self.viewport.get_height()
                center_x = view_w / 2.0
                center_y = view_h / 2.0
                
                self.base_offset_x = center_x - ((center_x - self.base_offset_x) * zoom_factor)
                self.base_offset_y = center_y - ((center_y - self.base_offset_y) * zoom_factor)
                handled = True

        # reset view keybind
        elif keyval == Gdk.KEY_Escape:
            self.reset_view()
            return True # exit bc dont need to update transform with reset_view

        elif keyval == Gdk.KEY_space:
            if self.player:
                has_pos, position = self.player.query_position(Gst.Format.TIME)
                has_dur, duration = self.player.query_duration(Gst.Format.TIME)

                is_finished = has_pos and has_dur and duration > 0 and (duration - position) < 100_000_000

                if is_finished:
                    self.player.seek_simple(
                        Gst.Format.TIME,
                        Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                        0
                    )
                    self.player.set_state(Gst.State.PLAYING)
                    handled = True
                
                else:
                    _, state, _ = self.player.get_state(0)

                    if state == Gst.State.PLAYING:
                        self.player.set_state(Gst.State.PAUSED)
                        handled = True
                    elif state == Gst.State.PAUSED:
                        self.player.set_state(Gst.State.PLAYING)
                        handled = True

        if handled:
            self.is_fitted = False
            self.offset_x = self.base_offset_x
            self.offset_y = self.base_offset_y
            self.update_transform()

        return handled

class ImageViewerApp(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="com.example.ImageViewer",
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        Gst.init(None)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = ImageViewer(self)
        win.present()

    def do_open(self, files, n_files, hint):
        self.do_activate()
        win = self.props.active_window

        if n_files > 0:
            file_path = files[0].get_path()
            if file_path:
                win.load_file(file_path)
        

if __name__ == "__main__":
    app = ImageViewerApp()
    app.run(sys.argv)
