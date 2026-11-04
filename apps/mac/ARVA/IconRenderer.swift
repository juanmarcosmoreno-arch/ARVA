import AppKit

/// `ARVA --render-iconset LOGO.png OUT.iconset`, run by scripts/build-mac-app.sh at build time: draws the logo,
/// fitted (whatever its aspect ratio) and centred on a white rounded square as macOS icons are, at every size an
/// .iconset needs; iconutil then makes ARVA.icns from it. No window is opened. The logo is the 1254 px master
/// (docs/brand/arva-logo-1254.png), so every size up to 512@2x (1024 px) is drawn by scaling it down, never up; its
/// transparent margins are left out first, so the logo is centred on what is visible.
enum IconRenderer {
    static func render(source: String, iconset: String) -> Int32 {
        guard let data = FileManager.default.contents(atPath: source),
              let bitmap = NSBitmapImageRep(data: data), let full = bitmap.cgImage,
              full.width > 0, full.height > 0 else {
            FileHandle.standardError.write("cannot read \(source)\n".data(using: .utf8)!)
            return 1
        }
        let visible = visibleBounds(full).flatMap { full.cropping(to: $0) } ?? full
        let logoSize = NSSize(width: visible.width, height: visible.height)
        let logo = NSImage(cgImage: visible, size: logoSize)
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

    /// The smallest rectangle holding every pixel that is not (almost) fully transparent, in the image's pixel
    /// coordinates with the origin at the top left (as CGImage.cropping(to:) takes them); nil when the image cannot be
    /// read or is fully transparent.
    static func visibleBounds(_ image: CGImage, alphaThreshold: UInt8 = 8) -> CGRect? {
        let width = image.width
        let height = image.height
        guard width > 0, height > 0 else { return nil }
        var pixels = [UInt8](repeating: 0, count: width * height * 4)
        var minX = width, minY = height, maxX = -1, maxY = -1
        let drawn: Bool = pixels.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(data: buffer.baseAddress, width: width, height: height, bitsPerComponent: 8,
                                          bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.clear(CGRect(x: 0, y: 0, width: width, height: height))
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard drawn else { return nil }
        // A bitmap context keeps its rows top first: row 0 of the buffer is the top of the image.
        for y in 0..<height {
            let row = y * width * 4
            for x in 0..<width where pixels[row + x * 4 + 3] > alphaThreshold {
                if x < minX { minX = x }
                if x > maxX { maxX = x }
                if y < minY { minY = y }
                if y > maxY { maxY = y }
            }
        }
        guard maxX >= minX, maxY >= minY else { return nil }
        return CGRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1)
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
        // The visible logo fits in 68% of the tile, keeping its aspect ratio (padded, never stretched): about the
        // size the earlier 164 px logo, with its own transparent margin, had in 72%.
        let box = tile.width * 0.68
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
