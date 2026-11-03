import AppKit

/// `ARVA --render-iconset LOGO.png OUT.iconset`, run by scripts/build-mac-app.sh at build time: draws the logo,
/// fitted (whatever its aspect ratio) and centred on a white rounded square as macOS icons are, at every size an
/// .iconset needs; iconutil then makes ARVA.icns from it. No window is opened.
enum IconRenderer {
    static func render(source: String, iconset: String) -> Int32 {
        guard let logo = NSImage(contentsOfFile: source),
              let rep = logo.representations.first, rep.pixelsWide > 0, rep.pixelsHigh > 0 else {
            FileHandle.standardError.write("cannot read \(source)\n".data(using: .utf8)!)
            return 1
        }
        let logoSize = NSSize(width: rep.pixelsWide, height: rep.pixelsHigh)
        let out = URL(fileURLWithPath: iconset, isDirectory: true)
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        for points in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let pixels = points * scale
                let name = scale == 1 ? "icon_\(points)x\(points).png" : "icon_\(points)x\(points)@2x.png"
                guard let png = draw(logo: logo, logoSize: logoSize, pixels: pixels) else { return 1 }
                do { try png.write(to: out.appendingPathComponent(name)) } catch { return 1 }
            }
        }
        return 0
    }

    private static func draw(logo: NSImage, logoSize: NSSize, pixels: Int) -> Data? {
        guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
              let context = NSGraphicsContext(bitmapImageRep: bitmap) else { return nil }
        let side = CGFloat(pixels)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = context
        context.imageInterpolation = .high
        NSColor.clear.set()
        NSRect(x: 0, y: 0, width: side, height: side).fill()
        // Apple's icon grid: an 824/1024 rounded square with a corner radius of about 185/1024.
        let inset = side * 100 / 1024
        let tile = NSRect(x: inset, y: inset, width: side - 2 * inset, height: side - 2 * inset)
        let radius = tile.width * 0.225
        let path = NSBezierPath(roundedRect: tile, xRadius: radius, yRadius: radius)
        if pixels >= 64 {
            let shadow = NSShadow()
            shadow.shadowColor = NSColor.black.withAlphaComponent(0.28)
            shadow.shadowBlurRadius = side * 10 / 1024
            shadow.shadowOffset = NSSize(width: 0, height: -side * 6 / 1024)
            NSGraphicsContext.saveGraphicsState()
            shadow.set()
            NSColor.white.setFill()
            path.fill()
            NSGraphicsContext.restoreGraphicsState()
        }
        let gradient = NSGradient(starting: NSColor.white, ending: NSColor(calibratedWhite: 0.93, alpha: 1))
        gradient?.draw(in: path, angle: -90)
        // The logo fits in 72% of the tile, keeping its aspect ratio (a non-square logo is padded, never stretched).
        let box = tile.width * 0.72
        let scale = min(box / logoSize.width, box / logoSize.height)
        let drawn = NSSize(width: logoSize.width * scale, height: logoSize.height * scale)
        let target = NSRect(x: tile.midX - drawn.width / 2, y: tile.midY - drawn.height / 2,
                            width: drawn.width, height: drawn.height)
        logo.draw(in: target, from: .zero, operation: .sourceOver, fraction: 1)
        context.flushGraphics()
        NSGraphicsContext.restoreGraphicsState()
        return bitmap.representation(using: .png, properties: [:])
    }
}
