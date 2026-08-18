# telegram-freelance-bot

A complete Telegram freelance marketplace bot with job posting, bidding, ratings, reports, and admin controls. All features accessible via inline buttons - only `/start` command needed!

---

## ✨ Features

### 👤 User Features
- **Job Board**: Browse and apply for jobs
- **Post Jobs**: Create job listings with title, description, category, budget, and contact info
- **Role Selection**: Choose between Client, Freelancer, or Both
- **Currency Support**: 13 currencies (USD, EUR, NGN, GBP, etc.)
- **Rating System**: Rate users 1-5 stars after job completion
- **Profile Management**: View your profile, rating, and job history
- **Report System**: Report scam users with detailed reasons

### 🛡️ Anti-Scam System
- **Auto-Warnings**: Users get warned after each report
- **Auto-Ban**: Automatic ban after 5 reports
- **Unban with Stars**: Pay 50 Stars as gift to unban
- **Admin Verification**: Payments verified by admins before unban

### 👑 Admin Features
- **Dashboard**: View bot statistics
- **Broadcast**: Send messages with images and buttons to all users
- **Report Management**: View, resolve, or dismiss scam reports
- **Payment Management**: View and confirm unban payments
- **User Management**: Ban, unban, or make users admin
- **Statistics**: Detailed bot usage statistics

### 💰 Supported Currencies
| Currency | Symbol | Emoji |
|----------|--------|-------|
| US Dollar | $ | 🇺🇸 |
| Euro | € | 🇪🇺 |
| British Pound | £ | 🇬🇧 |
| Nigerian Naira | ₦ | 🇳🇬 |
| Canadian Dollar | C$ | 🇨🇦 |
| Australian Dollar | A$ | 🇦🇺 |
| Indian Rupee | ₹ | 🇮🇳 |
| Japanese Yen | ¥ | 🇯🇵 |
| Chinese Yuan | ¥ | 🇨🇳 |
| Brazilian Real | R$ | 🇧🇷 |
| South African Rand | R | 🇿🇦 |
| Kenyan Shilling | KSh | 🇰🇪 |
| Ghanaian Cedi | ₵ | 🇬🇭 |
| Egyptian Pound | E£ | 🇪🇬 |

---

## 📋 Prerequisites

- Python 3.8 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Telegram account (for receiving Star gifts)

---

## 🚀 Installation

### 1. Clone or Download
```bash
# Create project folder
mkdir telegram-freelance-bot
cd telegram-freelance-bot
