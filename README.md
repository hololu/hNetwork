# hNetwork 🌐

**Çoklu arayüz + çoklu VLAN destekli, modern ağ tarayıcı** (eski `my_network_scanner` projesinin sıfırdan yeniden yazılmış hâli).

> © 2026 Mustafa ÖZKAYA · MIT Lisansı · [github.com/hololu/hNetwork](https://github.com/hololu/hNetwork)

## Özellikler
- ✅ **Çoklu arayüz taraması** — `eth0`, `wlan0`, `docker0` ... hepsini tek seferde tarayın
- ✅ **Çoklu VLAN taraması** — `eth0.10`, `eth0.20` (802.1q sub-interface) otomatik algılanır
- ✅ Hedef olarak **arayüz adı / VLAN / CIDR / IP aralığı** karışık kullanılabilir
- ✅ **Gerçek tarama, root/nmap gerektirmez** — saf-Python motoru (ping sweep + TCP socket + ARP tablosu)
  - root + nmap varsa otomatik olarak ARP/nmap motoruna geçer (sessiz cihazları da yakalar)
- ✅ MAC → üretici (OUI) tespiti — tam **IEEE OUI veritabanı** (39.8k kayıt) + `mac-vendor.txt` birleşimi
- ✅ Hostname çözümleme, cihaz tipi tespiti + güven skoru
- ✅ Modern web arayüzü:
  - **Açık / Koyu tema** geçişi (tercih hatırlanır)
  - **Sol menü aç/kapa** (☰ butonu, tercih hatırlanır)
  - Canlı ilerleme çubuğu (gerçek yüzde)
  - Cihaz **türü pill'lerine tıklayarak filtreleme**
  - **Sayfalama** — sayfada kaç kayıt görüneceği seçilebilir (10/25/50/100/Tümü)
  - Arama kutusu (IP, host, vendor, tip)
  - **TXT / CSV / JSON export**
  - **Periyodik otomatik tarama** zamanlayıcısı (1dk–1sa aralık)
- ✅ **Cihaz Detay Modalı** (listeden satıra tıkla):
  - IP, MAC, Hostname, Üretici, Tür, Durum, Ağ, Arayüz, Son görülme
  - **Port yeniden tarama** — taranacak **port aralığını girebilirsiniz** (`1-1000, 22, 80, 443, 3389`)
  - **Wake-on-LAN (WOL)** — cihazı uzaktan uyandırma
  - **Kopyala** (tek cihaz JSON) ve **Export** (TXT / JSON)
- ✅ CLI aracı (`hnetwork eth0 eth0.10 10.0.0.0/24`)
- ✅ **Docker desteği** — multi-arch (amd64 + arm64), `host` network modu

## Kurulum
```bash
cd calismalar/hnetwork
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
# veya: pip install -e .
```

## Çalıştırma
```bash
# Web arayüzü (http://localhost:5883)
python -m hnetwork.web

# CLI
hnetwork --list-interfaces
hnetwork eth0 eth0.10 192.168.1.0/24 --profile full
hnetwork --update-oui mac-vendor.txt   # MAC üretici DB'sini dosyadan güncelle
hnetwork --update-oui                  # IEEE'den online güncelle
```

> **root + nmap** varsa uygulama daha derin tarama yapar (ARP ile sessiz cihazlar, servis/OS parmak izi).
> Aksi hâlde güvenli şekilde **saf-Python gerçek tarama** yapar (ping + TCP socket + ARP tablosu). Demo/simülasyon modu yoktur.

## Web Arayüzü Kılavuzu
- **☰** (sol üst) — sol menüyü gizle/göster
- **☀/🌙** (sağ üst) — açık/koyu tema
- **Arayüzler & VLAN** — arayüz/VLAN kutuları, "Tümünü Seç / Temizle / Yerel ağlar" butonları
- **Tarama Seçenekleri** — profil (basic/full), çevrimdışı dahil, "Taramayı Başlat"
- **Periyodik Otomatik Tarama** — etkin + aralık seç → arka planda tekrarlanan tarama
- **Cihazlar** — sayfa boyutu seçici, TXT/CSV/JSON export, tür pill filtresi, arama
- **Cihaza tıkla** → Detay penceresi: port aralığı gir + "Yeniden Tara", "WOL Gönder", "Kopyala", "Export"
- **Özet** — toplam/çevrimiçi/hedef/tip sayıları + tür dağılımı (tıklanabilir)

## Mimari
```
hnetwork/
├── config.py      # kalıcı ayarlar (JSON)
├── interfaces.py  # arayüz / VLAN / hedef çözümleme
├── oui.py         # MAC üretici veritabanı + IEEE/mac-vendor.txt import
├── detection.py   # cihaz tipi tespiti
├── scanner.py     # ana tarama motoru (çoklu hedef, gerçek tarama)
├── web.py         # Flask uygulaması + REST API + periyodik scheduler
├── cli.py         # komut satırı aracı
├── bump_version.py# versiyon otomatik artış scripti
└── templates/     # modern web arayüzü (tema + sayfalama + modal + export)
```

## REST API
| Endpoint | Açıklama |
|----------|----------|
| `GET /api/interfaces` | Mevcut arayüzler |
| `GET /api/vlans` | VLAN sub-interface'leri |
| `POST /api/scan` | Tarama başlat (`{targets, profile, include_offline}`) |
| `GET /api/progress` | Canlı ilerleme (gerçek yüzde) |
| `POST /api/stop` | Taramayı durdur |
| `GET /api/results` | Bulunan cihazlar (tümü, özet dahil) |
| `GET /api/devices` | Bulunan cihazlar (liste) |
| `GET /api/device/<ip>` | Tek cihaz detayı |
| `POST /api/device/<ip>/ports` | Tek cihaz port yeniden tarama (`{ports:"1-1000,22,80"}`) |
| `POST /api/device/<ip>/wol` | Tek cihaza WOL magic packet gönder |
| `GET /api/export/<fmt>` | Export: `txt` / `csv` / `json` (dosya indirir) |
| `GET/POST /api/schedule` | Periyodik tarama durumu/ayarı |

## Versiyon Yönetimi
Her derleme/push öncesi patch versiyonunu otomatik artırın:
```bash
python bump_version.py          # 2.0.0 -> 2.0.1 (patch)
python bump_version.py --minor  # 2.0.0 -> 2.1.0 (minor)
python bump_version.py --major  # 2.0.0 -> 3.0.0 (major)
```
Script `hnetwork/__init__.py` ve `pyproject.toml` içindeki versiyonu senkron günceller.

## Docker (Proxmox / CasaOS)
Çoklu arayüz + VLAN taraması için `host` network modu önerilir.
```bash
# 1) Build + run (Proxmox x86_64 veya CasaOS/Pi ARM64)
docker build -t hnetwork:local .
docker run -d --name hnetwork --network host --restart unless-started \
  -v hnetwork-data:/app/data hnetwork:local
# → http://<sunucu-IP>:5883
```
Detaylı rehber: [README_DOCKER.md](README_DOCKER.md)

## Geliştirme İş Akışı
- **Kod yazımı:** Aider (qwen2.5-coder:7b, 2080 Ti GPU) ile `diff` edit-format
- **Koordinasyon:** Hermes Agent (commit / push / Docker / test / rapor)
- OpenCode ve Claude Code kullanılmamaktadır (credential/config sorunları)

## Lisans
MIT — bkz. [LICENSE](LICENSE). © 2026 Mustafa ÖZKAYA.
