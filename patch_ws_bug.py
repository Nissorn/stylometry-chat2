import os

file_path = "frontend/src/App.svelte"
with open(file_path, "r") as f:
    text = f.read()

old_onclose = """    ws.onclose = (event) => {
      console.log("WebSocket Disconnected", event.code);
      ws = null;
      if (event.code === 4001) {
        forceLockout();
      }
    };"""

new_onclose = """    const thisWs = ws;
    thisWs.onclose = (event) => {
      console.log("WebSocket Disconnected", event.code);
      // Only set ws to null if the active global ws is still THIS socket.
      // This prevents race conditions when switching chats rapidly.
      if (ws === thisWs) {
        ws = null;
      }
      if (event.code === 4001) {
        forceLockout();
      }
    };"""

text = text.replace(old_onclose, new_onclose)

with open(file_path, "w") as f:
    f.write(text)

print("patched ws onclose bug")
