# 🛡️ Thai-Stylometry Identity Continuous Authentication

ระบบพิสูจน์ตัวตนต่อเนื่อง (Continuous Authentication) ด้วย Stylometry สำหรับการแชตแบบเรียลไทม์

![Status](https://img.shields.io/badge/Status-Stable%20Milestone-success)
![Frontend](https://img.shields.io/badge/Frontend-Svelte%20%2B%20Vite-orange)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688)
![ML](https://img.shields.io/badge/ML-XGBoost%20%2B%20CharCNN-blue)

---

## 🎯 1) Project Title & Overview

### Continuous Authentication via Stylometry คืออะไร?

แทนที่จะ “ล็อกอินครั้งเดียวแล้วเชื่อใจตลอด session” โปรเจกต์นี้ใช้แนวคิด **Continuous Authentication** โดยเฝ้าดูรูปแบบการพิมพ์ข้อความของผู้ใช้ (Stylometric signals) ระหว่างแชต และอัปเดต **Trust Score** แบบต่อเนื่องผ่าน WebSocket

เมื่อพฤติกรรมการพิมพ์เริ่ม “ไม่เหมือนเจ้าของบัญชี” ระบบจะลด Trust Score และสามารถล็อก session ได้อัตโนมัติเมื่อความเสี่ยงสูง

### เหมาะกับใคร?

- 👩‍🎓 นักศึกษา: ใช้เป็นต้นแบบโครงงาน Security + AI + Realtime Systems
- 👨‍💻 นักพัฒนา: ศึกษา architecture แบบ microservice + low-latency scoring
- 🧪 นักวิจัย: ทดสอบ trade-off ระหว่าง False Acceptance / False Rejection ในบริบทภาษาไทย

---

## 🏗️ 2) Architecture & Tech Stack

### High-Level Architecture

~~~mermaid
flowchart LR
    U[User on Browser] --> F[Svelte Frontend :5173]
    F <--> |REST + WebSocket| B[FastAPI Backend :8000]
    B --> |HTTP /predict + /train| M[FastAPI ML Service :8001]
    B --> D[(SQLite app.db)]
    B --> W[/ml_workspace/data]
    M --> WM[/ml_workspace/models]
    M --> C[CharCNN + Stylometric Features + TF-IDF + XGBoost]
~~~

### Tech Stack Summary

| Layer | Technology |
|---|---|
| Frontend | Svelte + Vite + Tailwind + DaisyUI |
| API / Auth / WS | FastAPI + SQLAlchemy + JWT + TOTP + WebSocket |
| ML Service | FastAPI + PyTorch + scikit-learn + XGBoost |
| Fusion Modeling | CharCNN Features + Stylometric Meta Features + TF-IDF Stacking LR + XGBoost |
| Realtime Transport | WebSocket endpoint (/ws/chat) |
| Data & Persistence | SQLite (backend), files in /ml_workspace (baseline + user models) |

### Main Services and Default Ports

- 🌐 Frontend: http://localhost:5173
- 🔧 Backend API: http://localhost:8000
- 🤖 ML Service API: http://localhost:8001

---

## 🧠 3) The Trust Score Logic (Core Innovation)

ระบบไม่ได้ตัดสินจากข้อความเดียวแบบแข็งทื่อ แต่ใช้แนวทาง “ค่อย ๆ ตัดสินใจ” เพื่อลดทั้ง False Acceptance และ False Rejection

### 3.1 Grace Period (20 messages)

- ระหว่างเริ่มใช้งานครั้งแรก ระบบเก็บ baseline ของผู้ใช้
- เมื่อ baseline ครบอย่างน้อย 20 ข้อความ ระบบจะ train โมเดลรายผู้ใช้
- ก่อนมีโมเดล จะอยู่ในสถานะ cold_start

### 3.2 Red / Gray / Green Zone

ระบบดู latest_message_confidence แล้วปรับ Trust Score ดังนี้

- 🔴 Red Zone: score < 0.50
  - baseline < 100 บรรทัด: ลด 10 คะแนน
  - baseline >= 100 บรรทัด: ลด 25 คะแนน
- ⚪ Gray Zone: 0.50 <= score <= 0.85
  - ไม่เพิ่ม/ไม่ลด (กันการลงโทษจากข้อความกำกวม)
- 🟢 Green Zone: score > 0.85
  - เพิ่ม +5 คะแนน (สูงสุด 100)

### 3.3 Session Lock Rule

- ถ้าเปิด Security Enforcement และ Trust Score < 40
- ระบบปิด WebSocket session ด้วย lockout code อัตโนมัติ

แนวคิดนี้ช่วยให้ระบบมีความ “นุ่มนวล” พอสำหรับการใช้งานจริง โดยไม่ยอมรับผู้บุกรุกง่ายเกินไป

---

## ✅ 4) Prerequisites

ต้องมีเครื่องมือเหล่านี้ก่อนเริ่ม

- Python 3.10+ (แนะนำ 3.10 หรือ 3.11)
- Node.js 20+ และ npm
- Git
- (ถ้าใช้ Docker) Docker Desktop + Docker Compose

ตรวจสอบเวอร์ชัน

~~~bash
python3 --version
node --version
npm --version
docker --version
docker compose version
~~~

---

## 💻 5) Step-by-Step Local Installation (NON-DOCKER, ละเอียดมาก)

> วิธีนี้เหมาะกับคนที่ไม่ใช้ Docker และต้องเปิด 3 หน้าต่าง Terminal พร้อมกัน

## 5.0 Clone และเข้าโฟลเดอร์โปรเจกต์

~~~bash
git clone <your-repo-url>
cd stylometry-chat2
~~~

## 5.1 เตรียมโฟลเดอร์ shared workspace สำหรับ baseline/model (สำคัญมาก)

โค้ดปัจจุบันอ่าน/เขียนไฟล์ที่ path คงที่ คือ /ml_workspace

~~~bash
sudo mkdir -p /ml_workspace/data /ml_workspace/models
sudo chown -R $(whoami) /ml_workspace
~~~

## 5.2 ทำให้ Backend หา ML Service เจอในโหมด non-docker

Backend เรียก ML URL เป็น host ชื่อ stylometry-ml-service โดยค่าเริ่มต้น

ให้เพิ่ม host alias ในเครื่อง

~~~bash
echo "127.0.0.1 stylometry-ml-service" | sudo tee -a /etc/hosts
~~~

> ถ้าเคยเพิ่มแล้ว ไม่ต้องเพิ่มซ้ำ

---

## 5.3 เปิด Terminal 1: Backend (FastAPI :8000)

~~~bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# optional: กำหนด env ให้ชัดเจน
export DATABASE_URL="sqlite:///./app.db"
export SECRET_KEY="supersecret"

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
~~~

เมื่อรันสำเร็จ จะเข้าได้ที่

- API Root: http://localhost:8000
- Swagger: http://localhost:8000/docs

---

## 5.4 เปิด Terminal 2: ML Service (FastAPI :8001)

~~~bash
cd stylometry-ml-service
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
~~~

เมื่อรันสำเร็จ: http://localhost:8001

---

## 5.5 เปิด Terminal 3: Frontend (Svelte :5173)

~~~bash
cd frontend
npm install
npm run dev
~~~

เปิดเว็บที่

- http://localhost:5173

---

## 5.6 ลำดับการทดสอบที่แนะนำ

1. สมัครผู้ใช้ใหม่จากหน้าเว็บ
2. ล็อกอิน
3. เปิด Security Enforcement (ค่าเริ่มต้นเปิดอยู่)
4. พิมพ์ข้อความอย่างต่อเนื่องเพื่อเก็บ baseline
5. เมื่อ baseline ถึงเกณฑ์ ระบบจะ trigger training แล้วเข้าสู่ active scoring

---

## 🐳 6) Step-by-Step Docker Installation (Easy Way)

ถ้าคุณสะดวก Docker วิธีนี้ง่ายที่สุด

### 6.1 ตรวจสอบ path ที่ mount ใน docker-compose.yml

ไฟล์ docker-compose.yml ใช้ volume ภายนอกแบบ absolute path

- ./backend:/app
- ./frontend:/app
- ./stylometry-ml-service:/app
- /Users/onis2/Project/StylometryAI:/ml_workspace

ถ้าเครื่องคุณไม่มี path นี้ ให้แก้เป็น path ที่มีจริงก่อน (เช่นโฟลเดอร์ในเครื่องของคุณ)

### 6.2 สั่งรันทุก service

~~~bash
docker compose up --build
~~~

### 6.3 เข้าใช้งาน

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- ML Service: http://localhost:8001

หยุดระบบ

~~~bash
docker compose down
~~~

---

## 🧪 7) Offline Pre-training (Important)

แม้ใน repo จะมีไฟล์ base_char_cnn.pth และ base_char_cnn_vocab.json อยู่แล้ว แต่แนะนำให้รัน pre-training ใหม่เมื่อมีข้อมูลเจ้าของบัญชีจริง เพื่อให้ baseline model เหมาะกับโดเมนของคุณมากขึ้น

สคริปต์: scripts/train_cnn_offline.py

### 7.1 รันด้วย environment ของ ML Service

จาก root ของโปรเจกต์

~~~bash
# สร้าง/ใช้ venv จากฝั่ง ML Service ก่อน
cd stylometry-ml-service
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cd ..

python3 scripts/train_cnn_offline.py \
  --inbox_dir "/path/to/messages/inbox" \
  --owner_name "Your Name" \
  --epochs 5 \
  --output_dir stylometry-ml-service/app
~~~

ผลลัพธ์ที่ต้องได้

- stylometry-ml-service/app/base_char_cnn.pth
- stylometry-ml-service/app/base_char_cnn_vocab.json

### 7.2 หลัง pre-training เสร็จ ต้องทำอะไรต่อ?

- โหมด non-docker: restart ML Service
- โหมด docker: build/restart container ใหม่

~~~bash
docker compose up --build stylometry-ml-service
~~~

---

## 🤖 8) Automated Testing ด้วย Auto-Injector (WebSocket Simulation)

ไฟล์ทดสอบ: scripts/auto_injector.py

เครื่องมือนี้จะส่งข้อความชุดใหญ่เข้า WebSocket เพื่อจำลองการพิมพ์ของ user จริง และดู trust updates จากเซิร์ฟเวอร์แบบ realtime

## 8.1 เตรียมไฟล์ข้อความ

มีไฟล์ตัวอย่างแล้วในโฟลเดอร์ scripts/data

- good_messages.txt
- good_messages2.txt
- impostor_messages.txt

## 8.2 ขอ JWT Token ก่อนยิง WebSocket

### สมัคร (ถ้ายังไม่มี user)

~~~bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_user","password":"demo_pass_123"}'
~~~

### ล็อกอินเพื่อเอา access_token

~~~bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo_user","password":"demo_pass_123"}'
~~~

คัดลอกค่า access_token ที่ได้

## 8.3 รัน Auto-Injector

~~~bash
# แนะนำให้ใช้ venv ฝั่ง backend เพราะมี dependency websockets อยู่แล้ว
cd backend
source .venv/bin/activate
cd ..

python3 scripts/auto_injector.py \
  --token "PASTE_ACCESS_TOKEN_HERE" \
  --file scripts/data/good_messages.txt \
  --count 30 \
  --security_on
~~~

ตัวอย่างทดสอบเชิงรุก (ข้อความแปลกปลอม)

~~~bash
python3 scripts/auto_injector.py \
  --token "PASTE_ACCESS_TOKEN_HERE" \
  --file scripts/data/impostor_messages.txt \
  --count 30 \
  --security_on
~~~

สิ่งที่ควรสังเกต

- trust_score ลดลงแรงเมื่อเข้า Red Zone ต่อเนื่อง
- ใน Gray Zone score จะไม่แกว่งโดยไม่จำเป็น
- หากต่ำกว่าเกณฑ์ lock ระบบจะปิด session อัตโนมัติ

---

## 📂 Project Structure (Quick View)

~~~text
stylometry-chat2/
├── docker-compose.yml
├── backend/
│   ├── requirements.txt
│   └── app/
├── frontend/
│   ├── package.json
│   └── src/
├── stylometry-ml-service/
│   ├── requirements.txt
│   └── app/
└── scripts/
    ├── train_cnn_offline.py
    ├── auto_injector.py
    └── data/
~~~

---

## 🔐 Security Notes

- SECRET_KEY ควรเปลี่ยนเป็นค่า random ที่ปลอดภัยในงาน production
- ค่าเริ่มต้น SQLite เหมาะกับ dev/test; production ควรใช้ DB server จริง
- ตั้งค่า CORS origin ให้ตรงโดเมนจริงก่อน deploy

---

## 🧭 Troubleshooting (เจอบ่อย)

### Backend ต่อ ML ไม่ได้ใน non-docker

- ตรวจ /etc/hosts ว่ามีบรรทัดนี้
  - 127.0.0.1 stylometry-ml-service
- ตรวจว่า ML service รันที่ port 8001 จริง

### สิทธิ์เขียน /ml_workspace ไม่พอ

~~~bash
sudo chown -R $(whoami) /ml_workspace
~~~

### โมเดล CNN ไม่ถูกโหลด

ดู log ML service ถ้าเจอข้อความเตือนว่า base_char_cnn.pth not found ให้รัน pre-training ใหม่ (หัวข้อ 7)

---

## 🚀 Suggested Next Milestones

- เพิ่ม dashboard สำหรับแสดง Trust Score timeline และเหตุผลรายข้อความ
- เพิ่ม evaluation pipeline: FAR, FRR, EER บนชุดข้อมูลไทยเฉพาะโดเมน
- เพิ่ม CI สำหรับ integration test ระหว่าง Backend-ML-WebSocket

---

## 📝 License / Academic Use

โปรเจกต์นี้เหมาะกับการเรียน การทดลอง และการต่อยอดงานวิจัย หากจะนำไปใช้งานจริงเชิงพาณิชย์ ควรเพิ่มการ hardening ด้าน security, observability และ privacy compliance เพิ่มเติม
