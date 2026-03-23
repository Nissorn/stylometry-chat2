"""
Offline CharCNN Pre-Training Script
====================================
Trains an AttentionSessionCNN on the user's Instagram/Facebook message data
(with Latin-1 → UTF-8 mojibake fix) and a Thai background corpus.

Output artefacts (written to stylometry-ml-service/app/):
  - base_char_cnn.pth   : trained model weights
  - base_char_cnn_vocab.json : char2idx mapping

Usage:
  python3 scripts/train_cnn_offline.py \
      --inbox_dir /Users/onis2/Project/StylometryAI/Stylometry/messages/inbox \
      --owner_name "O" \
      --epochs 5 \
      --output_dir stylometry-ml-service/app

The ML service will automatically load these weights on the next container restart.
"""

import os
import sys
import glob
import json
import random
import argparse
import numpy as np
from collections import Counter

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Offline CharCNN pre-trainer")
parser.add_argument("--inbox_dir", type=str,
                    default="/Users/onis2/Project/StylometryAI/Stylometry/messages/inbox",
                    help="Path to the messages/inbox directory with JSON exports")
parser.add_argument("--owner_name", type=str, default="O",
                    help="The sender_name that belongs to YOU (positive class)")
parser.add_argument("--epochs", type=int, default=5)
parser.add_argument("--batch_size", type=int, default=64)
parser.add_argument("--lr", type=float, default=0.001)
parser.add_argument("--max_len", type=int, default=256)
parser.add_argument("--vocab_size", type=int, default=150)
parser.add_argument("--output_dir", type=str, default="stylometry-ml-service/app")
args = parser.parse_args()

# -----------------------------------------------------------------------
# Device
# -----------------------------------------------------------------------
def get_device():
    if torch.cuda.is_available(): return torch.device("cuda")
    if torch.backends.mps.is_available(): return torch.device("mps")
    return torch.device("cpu")

DEVICE = get_device()
print(f"[INFO] Using device: {DEVICE}")

# -----------------------------------------------------------------------
# 1. Data Loading — replicates full_pipeline.py fix_encoding + load_all_data
# -----------------------------------------------------------------------
SYSTEM_PATTERNS = [
    "sent an attachment.", "sent a photo.", "Reacted",
    "Liked a message", "unsent a message"
]

def fix_encoding(text):
    """Fix Latin-1 → UTF-8 mojibake present in Facebook/Instagram JSON exports."""
    if not isinstance(text, str):
        return ""
    try:
        return text.encode('latin1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

def load_instagram_data(inbox_dir, owner_name):
    """Return (positive_texts, negative_texts) from Instagram JSON exports."""
    pattern = os.path.join(inbox_dir, "**", "message_1.json")
    files = glob.glob(pattern, recursive=True)
    print(f"[INFO] Found {len(files)} message JSON files in {inbox_dir}")

    positive_texts = []  # owner's messages
    negative_texts = []  # other people's messages

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[WARN] Skipping {fpath}: {e}")
            continue

        for msg in data.get("messages", []):
            sender = fix_encoding(msg.get("sender_name", ""))
            content = fix_encoding(msg.get("content", ""))

            if not content or not isinstance(content, str) or content.strip() == "":
                continue
            if any(p in content for p in SYSTEM_PATTERNS):
                continue

            if sender == owner_name:
                positive_texts.append(content.strip())
            else:
                negative_texts.append(content.strip())

    print(f"[INFO] Loaded {len(positive_texts)} owner messages (positive class)")
    print(f"[INFO] Loaded {len(negative_texts)} other messages (negative class)")
    return positive_texts, negative_texts

# -----------------------------------------------------------------------
# 2. Universal Background Corpus (fallback if Instagram negatives are sparse)
# -----------------------------------------------------------------------
UNIVERSAL_BG = [
    "การประชุมจะเริ่มในเวลา 10.00 น. ขอให้ทุกคนตรงต่อเวลาด้วยครับ",
    "ทางบริษัทขอขอบพระคุณที่ท่านให้ความสนใจในบริการของเรา",
    "วันนี้สภาพอากาศค่อนข้างแปรปรวน โปรดดูแลรักษาสุขภาพ",
    "เอกสารที่ส่งมาให้เมื่อวานได้รับครบถ้วนแล้วนะคะ ขอบคุณมากค่ะ",
    "ขออนุญาตแจ้งเปลี่ยนแปลงกำหนดการเดินทางในวันพรุ่งนี้",
    "ตลาดหุ้นวันนี้ปิดตลาดปรับตัวลดลงตามทิศทางตลาดต่างประเทศ",
    "รับทราบครับ จะดำเนินการให้เสร็จภายในวันศุกร์นี้",
    "คุณลูกค้าสามารถชำระเงินผ่านระบบคิวอาร์โค้ดได้เลยค่ะ",
    "เมื่อคืนฝนตกหนักมากเลย ถนนแถวบ้านติดสุดๆ",
    "สรุปยอดขายประจำเดือนนี้เดี๋ยวผมส่งให้ในอีเมลนะครับ",
    "โครงการนี้มีกำหนดการแล้วเสร็จภายในไตรมาสที่สามของปีหน้า",
    "เดี๋ยวแวะซื้อกาแฟก่อนเข้าออฟฟิศ มีใครเอาอะไรไหม",
    "ขอแสดงความเสียใจกับครอบครัวผู้สูญเสียด้วยครับ",
    "รบกวนช่วยตรวจสอบความถูกต้องของข้อมูลในตารางให้หน่อย",
    "พรุ่งนี้เรามีนัดคุยเรื่องโปรเจกต์ใหม่ตอนบ่ายโมงตรงนะ",
    "รัฐบาลประกาศมาตรการกระตุ้นเศรษฐกิจเฟสใหม่แล้ววันนี้",
    "ขออภัยในความไม่สะดวก ทางเราจะรีบปรับปรุงแก้ไขโดยเร็วที่สุด",
    "วันนี้ประชุมยาวมากเลย แทบจะไม่ได้พักทานข้าว",
    "สินค้าชิ้นนี้มีการรับประกัน 1 ปีนับจากวันที่ซื้อครับ",
    "สุขสันต์วันเกิด ขอให้มีความสุขมากๆ สุขภาพแข็งแรงนะ",
    "Please check the report I've sent you by email, thanks",
    "The meeting has been rescheduled to next Monday morning.",
    "Could you review these documents when you get a chance?",
    "I'll be a bit late today, probably around 10 minutes.",
    "Thanks for your help with the project, really appreciate it!",
    "Let me know when you're free so we can catch up.",
    "The wifi is acting up again, anyone else having this issue?",
    "lol yeah same here, happens every afternoon smh",
    "ok cool see you there at 7pm then",
    "wait what time does it start tho",
]

# -----------------------------------------------------------------------
# 3. CharVocab (mirrors fusion_models.py exactly)
# -----------------------------------------------------------------------
class CharVocab:
    def __init__(self, texts, max_size=150):
        chars = Counter()
        for text in texts:
            chars.update(str(text))
        self.char2idx = {"<PAD>": 0, "<UNK>": 1}
        for idx, (char, _) in enumerate(chars.most_common(max_size - 2), start=2):
            self.char2idx[char] = idx

    def encode(self, text, max_len=256):
        if not isinstance(text, str): text = ""
        indices = [self.char2idx.get(c, 1) for c in text[:max_len]]
        if len(indices) < max_len:
            indices += [0] * (max_len - len(indices))
        return list(indices)

    def __len__(self):
        return len(self.char2idx)

# -----------------------------------------------------------------------
# 4. Model (mirrors fusion_models.py exactly)
# -----------------------------------------------------------------------
class SharedCharCNN(nn.Module):
    def __init__(self, vocab_size, embed_dim=64, num_filters=128):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.conv1 = nn.Conv1d(embed_dim, num_filters, kernel_size=3, padding=1)
        self.pool1 = nn.MaxPool1d(kernel_size=2)
        self.conv2 = nn.Conv1d(num_filters, num_filters, kernel_size=5, padding=2)
        self.global_pool = nn.AdaptiveMaxPool1d(1)
        self.dropout = nn.Dropout(0.3)
        self.relu = nn.ReLU()

    def forward(self, x):
        x = self.embedding(x).permute(0, 2, 1)
        x = self.pool1(self.relu(self.conv1(x)))
        x = self.global_pool(self.relu(self.conv2(x))).squeeze(2)
        return self.dropout(x)

class AttentionLayer(nn.Module):
    def __init__(self, feature_dim=128, hidden_dim=64):
        super().__init__()
        self.attn = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1)
        )

    def forward(self, features):
        scores = self.attn(features)
        weights = torch.softmax(scores, dim=1)
        return torch.sum(features * weights, dim=1)

class AttentionSessionCNN(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.base_model = SharedCharCNN(vocab_size)
        self.attention = AttentionLayer(feature_dim=128)
        self.classifier = nn.Linear(128, 1)

    def forward(self, inputs, return_features=False):
        features_list = [self.base_model(x) for x in inputs]
        features = torch.stack(features_list, dim=1)  # (B, N, 128)
        context = self.attention(features)             # (B, 128)
        if return_features:
            return context
        return torch.sigmoid(self.classifier(context))

# -----------------------------------------------------------------------
# 5. Dataset
# -----------------------------------------------------------------------
class TextDataset(Dataset):
    def __init__(self, texts, labels, vocab, max_len=256):
        self.texts = texts
        self.labels = labels
        self.vocab = vocab
        self.max_len = max_len

    def __len__(self): return len(self.texts)

    def __getitem__(self, idx):
        encoded = self.vocab.encode(self.texts[idx], self.max_len)
        x = torch.tensor(encoded, dtype=torch.long)
        y = torch.tensor(self.labels[idx], dtype=torch.float)
        return x, y

# -----------------------------------------------------------------------
# 6. Training loop
# -----------------------------------------------------------------------
def train_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss = 0.0
    correct = 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        # Single-message mode: wrap in list of length 1 (N=1)
        out = model([x]).squeeze(1)
        loss = criterion(out, y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        correct += ((out > 0.5).float() == y).sum().item()
    return total_loss / len(loader), correct / len(loader.dataset)

# -----------------------------------------------------------------------
# 7. Main
# -----------------------------------------------------------------------
def main():
    # --- Load data ---
    pos_texts, neg_texts = load_instagram_data(args.inbox_dir, args.owner_name)

    if len(pos_texts) == 0:
        print("[ERROR] No owner messages found. Check --owner_name and --inbox_dir.")
        sys.exit(1)

    # Use real IG negatives; supplement with BG corpus if very few
    if len(neg_texts) < len(pos_texts):
        print(f"[WARN] Negative texts ({len(neg_texts)}) < positive ({len(pos_texts)}). "
              "Supplementing with Universal Background Corpus.")
        extra_needed = len(pos_texts) - len(neg_texts)
        neg_texts += random.choices(UNIVERSAL_BG, k=extra_needed)

    # 1:1 balance: sample negatives to match positives
    random.shuffle(neg_texts)
    neg_texts = neg_texts[:len(pos_texts)]

    all_texts = pos_texts + neg_texts
    all_labels = [1]*len(pos_texts) + [0]*len(neg_texts)

    print(f"\n[INFO] Training set: {len(pos_texts)} positive, {len(neg_texts)} negative = {len(all_texts)} total")

    # --- Vocab ---
    vocab = CharVocab(all_texts, max_size=args.vocab_size)
    print(f"[INFO] Vocabulary size: {len(vocab)}")

    # --- Dataset / Loader ---
    dataset = TextDataset(all_texts, all_labels, vocab, args.max_len)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)

    # --- Model ---
    model = AttentionSessionCNN(len(vocab)).to(DEVICE)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.BCELoss()

    # --- Train ---
    print()
    for epoch in range(1, args.epochs + 1):
        loss, acc = train_epoch(model, loader, criterion, optimizer, DEVICE)
        print(f"[Epoch {epoch}/{args.epochs}]  Loss: {loss:.4f}  Acc: {acc:.4f}")

    # --- Save ---
    os.makedirs(args.output_dir, exist_ok=True)
    weights_path = os.path.join(args.output_dir, "base_char_cnn.pth")
    vocab_path   = os.path.join(args.output_dir, "base_char_cnn_vocab.json")

    torch.save(model.state_dict(), weights_path)
    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(vocab.char2idx, f, ensure_ascii=False)

    print(f"\n[DONE] Model saved  → {weights_path}")
    print(f"[DONE] Vocab saved  → {vocab_path}")
    print(f"\nNext step: rebuild your Docker image so the ML service picks up the new weights.")
    print("  docker compose up --build ml_service")

if __name__ == "__main__":
    main()
