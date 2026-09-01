# Stage 0 deployment and test runbook

This runbook turns the connectivity implementation into a real Pi deployment.
It assumes the repository checkout is currently /home/pi/Botanika. The
production systemd templates use /opt/botanika; copy or clone the committed
checkout there before enabling services.

Cloudflare account actions below follow the official Tunnel flow: a domain on
Cloudflare is required for a published application, the tunnel is created in
Networking → Tunnels, and the published route points at the local service.
See the official Cloudflare setup guide:
https://developers.cloudflare.com/tunnel/setup/

## 1. Commit the source on the Pi

From the repository checkout:

~~~bash
cd /home/pi/Botanika
git status
git add .
git commit -m "feat: implement phone to Pi connectivity stage"
~~~

Keep secrets out of this commit. In particular, do not add /etc/botanika, a
tunnel token, Cloudflare credential JSON, cookies, or a private deployment
record. Push it to GitHub from an authenticated workstation when ready:

~~~bash
git push origin main
~~~

## 2. Run the local contract test before installing services

~~~bash
cd /home/pi/Botanika
python3 -m venv .venv
.venv/bin/python -m pip install -e 'backend[test]'
.venv/bin/python -m pytest -q
~~~

Expected result is 14 passing tests. Start the development origin in one
terminal:

~~~bash
.venv/bin/python -m uvicorn botanika.main:app \
  --app-dir backend/src --host 127.0.0.1 --port 8000
~~~

In a second terminal, verify it:

~~~bash
curl --fail http://127.0.0.1:8000/api/v1/health/live
curl --fail http://127.0.0.1:8000/api/v1/health/ready
~~~

Open http://127.0.0.1:8000/ on the Pi. Select a small, non-sensitive JPEG or
WebP plant crop and send it. Confirm the phone hash equals the Pi
content_hash, and confirm the readiness response still reports
"temporary_file_count": 0. Stop this development process before continuing.

## 3. Prepare the production checkout and user

These commands require administrator access. If /opt/botanika already has a
deployment, update it through your normal Git workflow rather than overwriting
machine-local state.

~~~bash
sudo useradd --system --home /opt/botanika --shell /usr/sbin/nologin botanika || true
sudo install -d -o botanika -g botanika /opt/botanika /etc/botanika
git archive --format=tar HEAD | sudo tar -x -C /opt/botanika
sudo chown -R botanika:botanika /opt/botanika
cd /opt/botanika
sudo -u botanika python3 -m venv /opt/botanika/.venv
sudo -u botanika /opt/botanika/.venv/bin/python -m pip install -e '/opt/botanika/backend'
~~~

Copy config/environments/connectivity.env.example to
/etc/botanika/botanika.env and edit it with sudoedit. Set the actual
Cloudflare team domain, Access application audience, and public owner email.
Keep these production values:

~~~text
BOTANIKA_ENVIRONMENT=production
BOTANIKA_ACCESS_REQUIRED=true
BOTANIKA_CSRF_REQUIRED=true
BOTANIKA_MAX_IMAGE_BYTES=5242880
BOTANIKA_MAX_REQUEST_BYTES=6291456
~~~

Restrict the file:

~~~bash
sudo chmod 600 /etc/botanika/botanika.env
~~~

## 4. Install and verify Nginx

~~~bash
sudo apt update
sudo apt install nginx
sudo install -m 0644 /opt/botanika/deploy/reverse_proxy/botanika.conf.example \
  /etc/nginx/sites-available/botanika
sudo ln -sfn /etc/nginx/sites-available/botanika /etc/nginx/sites-enabled/botanika
sudo unlink /etc/nginx/sites-enabled/default 2>/dev/null || true
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
~~~

The Nginx listener must be 127.0.0.1:8080, not 0.0.0.0:8080. Check it:

~~~bash
ss -ltnp | grep -E ':(80|8080)\b'
curl --fail http://127.0.0.1:8080/api/v1/health/live
~~~

The port 80 default page is no longer the Botanika entry point; the public
route will go through Cloudflare to port 8080.

## 5. Install and verify the backend service

~~~bash
sudo install -m 0644 /opt/botanika/deploy/systemd/botanika-backend.service \
  /etc/systemd/system/botanika-backend.service
sudo systemctl daemon-reload
sudo systemctl enable --now botanika-backend
sudo systemctl status botanika-backend --no-pager
curl --fail http://127.0.0.1:8000/api/v1/health/ready
~~~

Inspect the listeners again. FastAPI must bind only to 127.0.0.1:8000 and Nginx
only to 127.0.0.1:8080. From a second device on the Pi LAN, verify that the Pi
LAN address does not answer on either port.

## 6. Create Access and the named tunnel

In Cloudflare:

1. Add/verify the domain and choose the final hostname, for example
   botanika.example.com.
2. Create a self-hosted Access application for that exact hostname.
3. Enable email OTP and create an Allow policy containing only
   kisoreabhinav@gmail.com; do not use Everyone.
4. Create a named tunnel called botanika-pi-production.
5. Choose Linux/ARM64 and copy the tunnel token into a machine-local file. Do
   not place it in shell history or Git.
6. Add a Published application route for the final hostname with service URL
   http://127.0.0.1:8080.
7. Confirm the DNS record is proxied to the tunnel and does not contain the
   home public IP.

Install the official ARM64 cloudflared package using the command shown by the
Cloudflare dashboard/official documentation, then verify:

~~~bash
cloudflared --version
~~~

Create /etc/botanika/cloudflared.env using sudoedit:

~~~text
TUNNEL_TOKEN=PASTE_THE_TOKEN_ONLY_IN_THIS_MACHINE_LOCAL_FILE
~~~

Then lock it down and install the supplied unit:

~~~bash
sudo chmod 600 /etc/botanika/cloudflared.env
sudo install -m 0644 /opt/botanika/deploy/systemd/botanika-cloudflared.service \
  /etc/systemd/system/botanika-cloudflared.service
sudo systemctl daemon-reload
sudo systemctl enable --now botanika-cloudflared
sudo systemctl status botanika-cloudflared --no-pager
~~~

The tunnel unit now requires both botanika-backend.service and nginx.service,
so it cannot be considered started while either origin layer is absent. Check
logs without printing the environment file:

~~~bash
sudo journalctl -u botanika-cloudflared -n 50 --no-pager
~~~

## 7. Prove the public route and Access policy

Use the final hostname in a normal browser. In a private/incognito window:

1. Confirm the request is redirected to Cloudflare Access.
2. Sign in with kisoreabhinav@gmail.com and the received OTP.
3. Confirm the Botanika placeholder loads.
4. Try an unapproved address and confirm it is denied.
5. Confirm the browser status card says connected and the environment is
   production.

Do not use the Pi LAN IP for this test; the purpose is to prove the public
HTTPS/WSS path.

## 8. Prove the different-network crop flow

With the Pi on its normal Ethernet/Wi-Fi connection:

1. Turn Wi-Fi off on the phone and confirm cellular data is active.
2. Open the same https://botanika.example.com hostname.
3. Authenticate with Access if prompted.
4. Select a small test crop and record the phone-side SHA-256.
5. Send it and confirm the receipt dimensions, MIME, byte count, and
   content_hash match the phone preview.
6. Confirm the UI says the Pi discarded the crop.
7. Confirm on the Pi that no upload file remains:

~~~bash
find /opt/botanika/data/media/temp -type f ! -name .gitkeep -print
~~~

The command should print nothing. Repeat once with the phone on a different
Wi-Fi network from the Pi.

## 9. Prove reconnect, failure, and boot behavior

In the authenticated phone page:

1. Watch the status card change to disconnected when phone airplane mode is
   enabled briefly.
2. Disable airplane mode and wait for the status card to reconnect without a
   page reload.
3. Start an upload, interrupt connectivity, and confirm the crop remains
   available with Retry/Cancel. Cancel must clear it locally.
4. Stop Nginx, backend, and cloudflared one at a time. Confirm each failure is
   visible, then restart the service.
5. Reboot the Pi and record time until backend ready, Nginx ready, tunnel
   healthy, and the public page usable again.
6. Disconnect only the Pi's internet, confirm the phone reports unavailable,
   restore internet, and confirm cloudflared reconnects without DNS changes.

Useful checks:

~~~bash
systemctl is-active botanika-backend nginx botanika-cloudflared
ss -ltnp | grep -E ':(8000|8080)\b'
sudo journalctl -u botanika-backend -u botanika-cloudflared -b --no-pager
~~~

## 10. Record the Stage 0 result

Record the hostname, tunnel UUID, connector version, Pi architecture, and these
measurements outside Git: authenticated page load, ten liveness requests,
WebSocket reconnect time, crop size, upload duration, receipt duration, reboot
recovery, and internet-loss recovery. The YOLO detector, camera capture,
stability gate, and automatic crop generation are intentionally later stages;
their absence from this placeholder is expected.
