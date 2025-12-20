# 🚀 START HERE - Quick Run Guide

## ⚡ Fastest Way to Start (Windows)

### Option 1: One-Click Start (Easiest) ⭐

1. **Double-click this file:**
   ```
   start_production.bat
   ```

2. **Wait 30 seconds** for all services to start

3. **Open browser:** `http://localhost:8081`

4. **Done!** Start chatting and testing!

---

### Option 2: Manual Start (If script doesn't work)

Open **3 separate Command Prompt windows**:

#### Window 1 - Vision Server
```cmd
cd C:\Users\User\dental_chatbot
python run_vision_server.py
```

#### Window 2 - Rasa Server  
```cmd
cd C:\Users\User\dental_chatbot\rasa_bot\actions
rasa run --enable-api --port 5005
```

#### Window 3 - Rasa Actions
```cmd
cd C:\Users\User\dental_chatbot\rasa_bot\actions
rasa run actions --port 5055
```

Then open: `http://localhost:8081`

---

## ✅ Quick Checklist

Before starting:
- [ ] Python 3.8+ installed (`python --version`)
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Camera available (for testing)

After starting:
- [ ] Vision Server running (check Terminal 1)
- [ ] Rasa Server running (check Terminal 2)  
- [ ] Rasa Actions running (check Terminal 3)
- [ ] Browser opens to `http://localhost:8081`
- [ ] Camera access granted
- [ ] Chat working

---

## 🐛 Common Issues

| Problem | Solution |
|---------|----------|
| "Python not found" | Install Python, check "Add to PATH" |
| "Module not found" | Run `pip install -r requirements.txt` |
| "Port in use" | Close other programs or change ports |
| Camera not working | Check browser permissions, try Chrome/Edge |

---

## 📞 Need Help?

- See `QUICK_START_WINDOWS.md` for detailed instructions
- Check `DEPLOYMENT.md` for troubleshooting
- Verify all services are running on correct ports

---

**Ready? Run `start_production.bat` now!** 🚀

