# hnetwork — Docker Kurulum Rehberi

Çoklu arayüz + çoklu VLAN taraması yapan hnetwork, Docker container içinden
**`host` network modu** ile çalıştırıldığında sunucudaki tüm arayüzleri/VLANları görür
ve gerçek tarama yapar.

---

## 1) Proxmox (LXC Container veya VM)

### A) Container (CT) içinde Docker
LXC CT oluşturun, içine Docker kurun (CT'de `nesting` + `keyctl` açık olmalı).
Sonra CT içinde:

```bash
git clone https://github.com/hololu/hNetwork.git
cd hNetwork
docker compose up -d --build
```
Arayüz: `http://<CT-IP>:5883`

### B) Proxmox üzerinde Portainer (önerilen)
1. Portainer'ı Proxmox'a kurun (Portainer Stack veya App şablonu).
2. **Stacks → Add stack → Web editor**.
3. Aşağıdaki `docker-compose.yml` içeriğini yapıştırın.
4. **Deploy the stack**.

> `docker-compose.yml` bu depoda hazır gelir (`network_mode: host` ile).

---

## 2) CasaOS (Raspberry Pi / ARM)

CasaOS zaten Docker tabanlıdır.

1. CasaOS arayüzü → **App Store / App Management**.
2. Eğer "Custom App" / "Compose" seçeneği varsa, `docker-compose.yml` içeriğini yapıştırın.
3. Ya da SSH ile:
   ```bash
   git clone https://github.com/hololu/hNetwork.git
   cd hNetwork
   docker compose up -d --build
   ```
4. CasaOS'ta port otomatik algılanır; **hnetwork** kartı çıkar, tıklayınca `http://<Pi-IP>:5883` açılır.

> ARM (Pi 3/4/5) için image `linux/arm64` olarak build edilir — `docker-compose.yml`
> içindeki `platforms: [linux/amd64, linux/arm64]` sayesinde otomatik seçilir.

---

## 3) docker-compose.yml (hazır)

```yaml
services:
  hnetwork:
    build:
      context: .
      platforms:
        - linux/amd64
        - linux/arm64
    image: hnetwork:local
    container_name: hnetwork
    network_mode: host        # TÜM arayüz/VLAN görünür (gerekli)
    restart: unless-stopped
    volumes:
      - hnetwork-data:/app/data   # OUI DB + sonuçlar kalıcı
volumes:
  hnetwork-data:
```

**Bridge moda geçmek isterseniz** (host yerine): `network_mode: host` satırını silin,
`ports: ["5883:5883"]` ekleyin. Ancak bu durumda container sadece sunucu
IP'sini tarayabilir — çoklu arayüz/VLAN taraması için **host** önerilir.

---

## 4) Image'ı kendiniz build edin (multi-arch)

```bash
# Sadece mevcut mimari
docker build -t hnetwork:local .

# Çoklu mimari (push için — gerekiyorsa)
docker buildx create --name hn-builder --use
docker buildx build --platform linux/amd64,linux/arm64 \
  -t hnetwork:local --load .
```

## 5) Volumes / Kalıcılık
- `/app/data` → OUI veritabanı (`data/ieee_oui.json`) ve tarama sonuçları.
  Volume'a bağlanmazsa her container yeniden başlatıldığında OUI DB yeniden
  indirilir (internet gerekir).
- Konfigürasyon `data/config.json` içinde; volume'da kalır.

## 6) Yetkiler (gerçek tarama)
Uygulama container **içinde root** ile çalışır ve `host` network kullandığı için
ARP tabanlı gerçek tarama yapabilir. `nmap` image'a kuruludur; root+nmap varsa
uygulama otomatik olarak daha derin taramaya geçer.

## 7) Doğrulama
```bash
docker logs hnetwork          # "Running on 0.0.0.0:5883" görmelisiniz
curl http://localhost:5883/   # HTML dönüyorsa hazır
```
Tarayıcıdan `http://<sunucu-IP>:5883` açın → "Arayüzler & VLAN" kartında
sunucudaki tüm arayüzler + VLAN'lar listelenir.

---

## 8) 🚀 Hazır `docker run` komutları (build gerekmez)

En pratik yol — image'ı **siz build edip** container'ı tek satırda başlatırsınız.
Aşağıdaki komutlar **multi-arch** değildir; çalıştırdığınız makinenin
mimarisine uygun olanı kullının (Proxmox = amd64, Pi/CasaOS = arm64).

### A) Proxmox (x86_64 / LXC-CT veya VM)
```bash
# 1) Image'ı build et (amd64)
docker build -t hnetwork:local .
# 2) Host network ile başlat (tüm arayüz/VLAN görünür)
docker run -d --name hnetwork --network host --restart unless-stopped \
  -v hnetwork-data:/app/data hnetwork:local
# → http://<proxmox-CT-IP>:5883
```

### B) CasaOS / Raspberry Pi (ARM64)
```bash
# 1) Image'ı build et (arm64)
docker build -t hnetwork:local .
# 2) Host network ile başlat
docker run -d --name hnetwork --network host --restart unless-stopped \
  -v hnetwork-data:/app/data hnetwork:local
# CasaOS arayüzü otomatik "hnetwork" kartını gösterir
# → http://<pi-IP>:5883
```

### C) Bridge mod isterseniz (host yerine)
```bash
docker run -d --name hnetwork -p 5883:5883 --restart unless-stopped \
  -v hnetwork-data:/app/data hnetwork:local
```
> ⚠️ Bridge modda container **sadece sunucunun kendi IP'sini** tarar.
> Çoklu arayüz / VLAN taraması için **`--network host` (A/B) önerilir.**

### D) Güncelleme
```bash
docker stop hnetwork && docker rm hnetwork
docker build -t hnetwork:local .        # veya image'ı yeniden çekin
docker run -d --name hnetwork --network host --restart unless-stopped \
  -v hnetwork-data:/app/data hnetwork:local
```

> **Not:** `docker-compose.yml` hâlâ depoda — Portainer gibi
> compose tabanlı panel kullanıyorsanız onu da kullanabilirsiniz
> (bkz. bölüm 1-B / 2). Ancak tek-satır `docker run` çoğu
> durumda daha hızlıdır.
