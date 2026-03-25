import asyncio
import websockets
import argparse
import random
import json

async def run_injector(token, file_path, count, security_on):
    uri = f"ws://localhost:8000/ws/chat?token={token}"
    
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        
    messages_to_send = lines[:count] if count > 0 else lines
    
    if not messages_to_send:
        print(f"No messages found in {file_path}. Exiting.")
        return
        
    print(f"Loaded {len(messages_to_send)} messages from {file_path}.")
    
    # Randomly shuffle or preserve order? Usually better to preserve typing history, but we can just use linearly.
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Successfully connected to {uri}")
            
            # Start background listener
            async def listener():
                try:
                    while True:
                        msg = await websocket.recv()
                        data = json.loads(msg)
                        if data.get("type") == "trust_update":
                            status = data.get("status", "unknown")
                            trust = data.get("trust_score", "N/A")
                            conf = data.get("confidence", "N/A")
                            server_msg = data.get("message", "")
                            print(f"--> [SERVER] Trust: {trust} | Conf: {conf} | Status: {status} | {server_msg}")
                            
                            if status == "locked" or data.get("type") == "error":
                                print("--> [SERVER] Session Locked!")
                                
                        elif data.get("type") == "chat":
                            sender = data.get("sender", "?")
                            # Broadcast format uses 'message'; legacy echo used 'text'
                            text = data.get("message") or data.get("text", "")
                            print(f"    [CHAT from {sender}] {text}")
                except websockets.exceptions.ConnectionClosed as e:
                    print(f"\nConnection Closed! Code: {e.code}, Reason: {e.reason}")
                except Exception as e:
                    print(f"Listener Error: {e}")
                    
            listener_task = asyncio.create_task(listener())
            
            for i, text in enumerate(messages_to_send):
                payload = {
                    "message": text,
                    "enforce_security": security_on
                }
                print(f"\n[{i+1}/{len(messages_to_send)}] Sending: {text}")
                await websocket.send(json.dumps(payload))
                
                delay = random.uniform(1.5, 3.5)
                await asyncio.sleep(delay)
                
            print("\nFinished sending messages. Keeping connection open for 10 seconds to catch final replies...")
            await asyncio.sleep(10)
            listener_task.cancel()
            
    except ConnectionRefusedError:
        print(f"Failed to connect to {uri}. Is the backend running?")
    except Exception as e:
        print(f"Injector Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stylometry Auto-Injector")
    parser.add_argument("--token", required=True, help="JWT Token for authentication")
    parser.add_argument("--file", required=True, help="Path to text file containing messages")
    parser.add_argument("--count", type=int, default=0, help="Number of messages to inject (0 for all)")
    parser.add_argument("--security_on", action="store_true", help="Set enforce_security to True")
    
    args = parser.parse_args()
    asyncio.run(run_injector(args.token, args.file, args.count, args.security_on))
