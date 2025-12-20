# 🚀 Quick Start Guide - Windows

## Step-by-Step Instructions to Run the Project

### Prerequisites Check

1. **Check Python is installed:**
   ```cmd
   python --version
   ```
   Should show Python 3.8 or higher. If not, install from [python.org](https://www.python.org/downloads/)

### Method 1: Easy Way (Using Startup Script) ⭐ RECOMMENDED

1. **Open Command Prompt or PowerShell** in the project folder:
   ```cmd
   cd C:\Users\User\dental_chatbot
   ```

2. **Run the startup script:**
   ```cmd
   start_production.bat
   ```

   This will:
   - Create virtual environment (if needed)
   - Install dependencies
   - Start all 3 services in separate windows:
     - Vision Server (Port 8081)
     - Rasa Server (Port 5005)
     - Rasa Actions (Port 5055)

3. **Wait for all windows to open** (about 30 seconds)

4. **Open your browser** and go to:
   ```
   http://localhost:8081
   ```

5. **Test the system:**
   - Allow camera access when prompted
   - Type a message in the chat
   - Watch the emotion detection in real-time

### Method 2: Manual Start (3 Separate Terminals)

If you prefer to see each service separately:

#### Terminal 1 - Vision Server
```cmd
cd C:\Users\User\dental_chatbot
python run_vision_server.py
```
Wait for: `"Application startup complete"`

#### Terminal 2 - Rasa Server
```cmd
cd C:\Users\User\dental_chatbot\rasa_bot\actions
rasa run --enable-api --port 5005
```
Wait for: `"Starting Rasa server..."`

#### Terminal 3 - Rasa Actions
```cmd
cd C:\Users\User\dental_chatbot\rasa_bot\actions
rasa run actions --port 5055
```
Wait for: `"Action server running"`

#### Then Open Browser
Go to: `http://localhost:8081`

### Troubleshooting

#### "Python not found"
- Install Python from [python.org](https://www.python.org/downloads/)
- Make sure to check "Add Python to PATH" during installation

#### "Module not found" errors
```cmd
pip install -r requirements.txt
```

#### "Port already in use"
- Close any programs using ports 8081, 5005, or 5055
- Or change ports in `.env` file

#### Camera not working
- Check browser permissions
- Try Chrome or Edge (best compatibility)
- Make sure no other app is using the camera

### What to Expect

1. **Vision Server Window:**
   - Shows: "Starting Vision API server on 0.0.0.0:8081"
   - Shows: "Application startup complete"

2. **Rasa Server Window:**
   - Shows: "Starting Rasa server..."
   - Shows: "Rasa server is up and running"

3. **Rasa Actions Window:**
   - Shows: "Action server running"
   - Shows: "Starting action server..."

4. **Browser:**
   - Web interface loads
   - Camera feed appears
   - Chat window is ready

### Testing the System

1. **Test Vision API:**
   - Open: `http://localhost:8081/health`
   - Should show: `{"status": "healthy"}`

2. **Test Rasa API:**
   - Open: `http://localhost:5005/status`
   - Should show Rasa status

3. **Test Full System:**
   - Go to: `http://localhost:8081`
   - Allow camera access
   - Type "hello" in chat
   - Should get a response from the chatbot

### Stopping the Services

- **If using startup script:** Close all 3 windows that opened
- **If manual:** Press `Ctrl+C` in each terminal

### Next Steps

Once everything is running:
- Try different emotions (smile, frown, etc.)
- Test the chatbot with various questions
- Check the emotion detection values in the UI

Enjoy! 🎉

