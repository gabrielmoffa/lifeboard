import Cocoa

let path = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ""
guard !path.isEmpty else {
    print("Usage: set_wallpaper <image_path>")
    exit(1)
}

let workspace = NSWorkspace.shared
let url = URL(fileURLWithPath: path)

for screen in NSScreen.screens {
    do {
        try workspace.setDesktopImageURL(url, for: screen, options: [
            .imageScaling: NSImageScaling.scaleProportionallyUpOrDown.rawValue,
            .allowClipping: true
        ])
        print("Set wallpaper for: \(screen.localizedName)")
    } catch {
        print("Error for \(screen.localizedName): \(error)")
    }
}
