/**
 * LayaSDLC event-logging plugin for OpenCode (Stage 5, item 5.10).
 *
 * Logs every LayaSDLC tool invocation through the OpenCode logging API so
 * workflow transitions and model usage are auditable in the session log.
 *
 * The plugin registers no tools of its own -- the tools live in
 * `.opencode/tools/layasdlc.ts`. This file only subscribes to events.
 */

export const LayaSDLCPlugin = async ({ client }: any) => {
  return {
    event: async ({ event }: any) => {
      const type: string = event?.type ?? ""
      // Only log tool execution events to keep the session log focused.
      if (type !== "tool.execute.after") return
      try {
        await client.app.log({
          body: {
            service: "layasdlc",
            level: "info",
            message: `OpenCode tool executed: ${type}`,
          },
        })
      } catch {
        // Logging must never break a tool call.
      }
    },
  }
}

export default LayaSDLCPlugin
