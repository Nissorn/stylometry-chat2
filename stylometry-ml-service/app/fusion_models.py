import re
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from collections import Counter
from sklearn.base import BaseEstimator, TransformerMixin

# -----------------------------------------------------------------------------
# 1. Dataset & Vocab
# -----------------------------------------------------------------------------
class CharVocab:
    def __init__(self, texts, max_size=150):
        chars = Counter()
        for text in texts: chars.update(str(text))
        self.char2idx = {"<PAD>": 0, "<UNK>": 1}
        for idx, (char, _) in enumerate(chars.most_common(max_size - 2), start=2):
            self.char2idx[char] = idx
            
    def encode(self, text, max_len=256):
        if not isinstance(text, str): text = ""
        indices = [self.char2idx.get(c, 1) for c in text[:max_len]]
        if len(indices) < max_len: indices += [0] * (max_len - len(indices))
        return list(indices)
    
    def __len__(self): return len(self.char2idx)

# -----------------------------------------------------------------------------
# 2. Model Architecture (Deep Branch - 5 Inputs)
# -----------------------------------------------------------------------------
class SharedCharCNN(nn.Module):
    def __init__(self, vocab_size, embed_dim=64, num_filters=128):
        super(SharedCharCNN, self).__init__()
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
        super(AttentionLayer, self).__init__()
        self.attn = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1)
        )
    def forward(self, features): # (B, N, 128)
        scores = self.attn(features) # (B, N, 1)
        weights = F.softmax(scores, dim=1) # Softmax over N
        context = torch.sum(features * weights, dim=1) # (B, 128)
        return context

class AttentionSessionCNN(nn.Module):
    def __init__(self, vocab_size):
        super(AttentionSessionCNN, self).__init__()
        self.base_model = SharedCharCNN(vocab_size)
        self.attention = AttentionLayer(feature_dim=128)
        self.classifier = nn.Linear(128, 1)
        
    def forward(self, inputs, return_features=False):
        features_list = []
        for x in inputs:
            features_list.append(self.base_model(x))
            
        features = torch.stack(features_list, dim=1) # (B, N, 128)
        context = self.attention(features) # (B, 128)
        
        if return_features:
            return context
            
        logits = self.classifier(context)
        return torch.sigmoid(logits)

# -----------------------------------------------------------------------------
# 3. Classical Stylometry (Meta Branch)
# -----------------------------------------------------------------------------
class StylometricFeatureExtractor(BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        return self

    def transform(self, X, y=None):
        features = []
        for text in X:
            text = str(text)
            length = len(text)
            laugh_count = len(re.findall(r'5+|[hH]aha|ฮ่า+|อิอิ', text))
            elongation_count = len(re.findall(r'(.)\1{2,}|ๆ', text))
            punct_count = len(re.findall(r'[?!.]{2,}|~+', text))
            space_count = text.count(' ')
            features.append([length, laugh_count, elongation_count, punct_count, space_count])
        return np.array(features)
