/**
 * LayaSDLC plugin for OpenCode (Stage 5, item 5.10).
 *
 * Subscribes to tool execution events and logs them through the OpenCode
 * logging API so workflow transitions are auditable in the session log.
 *
 * The plugin registers no tools of its own — the tools live in
 * `.opencode/tools/layasdlc.ts`. This file only subscribes to events.
 */

import { Plugin } from "@opencode/plugin"

export default Plugin.define({
  id: "layasdlc",

  async setup(ctx) {
    const controller = new AbortController()

    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (event.type !== "tool.execute.after") continue
          try {
            await ctx.client.app.log({
              body: {
                service: "layasdlc",
                level: "info",
                message: `OpenCode tool executed: ${event.type}`,
              },
            })
          } catch {
            // Logging must never break a tool call.
          }
        }
      } catch {
        // Subscription ended (plugin unload); nothing to clean up.
      }
    })()

    // Cleanup: abort the event subscription when the plugin unloads.
    return () => controller.abort()
  },
})
