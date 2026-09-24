import Cocoa
import WebKit

// Resolved relative to the current user's home directory rather than hardcoded,
// so this works for anyone who clones the repo into ~/whoop on their own Mac —
// not just on the machine it was originally built on.
let refreshDir = NSHomeDirectory() + "/whoop"
let dashboardPath = refreshDir + "/index.html"

// Start the local server FIRST. It mints this run's token and writes it to .dashboard_token; the build
// below injects that token into index.html, and every request from the page must carry it. The old
// file is removed first so its reappearance means THIS server is up.
let tokenPath = refreshDir + "/.dashboard_token"
try? FileManager.default.removeItem(atPath: tokenPath)
let chatServer = Process()
chatServer.executableURL = URL(fileURLWithPath: "/bin/bash")
chatServer.arguments = ["-c", "cd \(refreshDir) && exec python3 chat_server.py"]
try? chatServer.run()
for _ in 0..<50 {                                    // up to 5 s for the server to bind and write it
    if FileManager.default.fileExists(atPath: tokenPath) { break }
    Thread.sleep(forTimeInterval: 0.1)
}

// Refresh data synchronously before showing the window (a couple seconds' delay is fine).
let task = Process()
task.executableURL = URL(fileURLWithPath: "/bin/bash")
task.arguments = ["-c", "cd \(refreshDir) && ./refresh.sh"]
try? task.run()
task.waitUntilExit()

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!

    func applicationDidFinishLaunching(_ notification: Notification) {
        let contentRect = NSRect(x: 0, y: 0, width: 1150, height: 880)

        let webView = WKWebView(frame: contentRect)
        if FileManager.default.fileExists(atPath: dashboardPath) {
            let fileURL = URL(fileURLWithPath: dashboardPath)
            webView.loadFileURL(fileURL, allowingReadAccessTo: fileURL.deletingLastPathComponent())
        } else {
            // First run before .env is configured / before the pipeline has ever
            // succeeded — show something actionable instead of a blank window.
            let message = """
            <html><body style="background:#0D1310;color:#E9F0E9;font-family:-apple-system,sans-serif;\
            padding:48px;line-height:1.6;">
            <h2>Dashboard data not found yet</h2>
            <p>Couldn't find <code>index.html</code> at <code>\(dashboardPath)</code>.</p>
            <p>Set up <code>.env</code> in that folder with your WHOOP credentials (and optionally an AI chat key), then run:</p>
            <pre style="background:#182019;padding:12px 16px;border-radius:8px;">cd \(refreshDir) && ./refresh.sh</pre>
            <p>Then reopen this app.</p>
            </body></html>
            """
            webView.loadHTMLString(message, baseURL: nil)
        }

        window = NSWindow(contentRect: contentRect,
                           styleMask: [.titled, .closable, .miniaturizable, .resizable],
                           backing: .buffered, defer: false)
        window.title = "WHOOP Dashboard"
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)

        NSApp.activate(ignoringOtherApps: true)

        // The chat/refresh server was started before the build (see the top of this file) and runs
        // for the life of the window; it holds the AI provider key and answers only token-bearing
        // requests from this page.
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        chatServer.terminate()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
