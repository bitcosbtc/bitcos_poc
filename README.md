# bitcos_poc
multiple account handling

pip install gunicorn

sudo nano /etc/systemd/system/fastapi.service
[Unit]
Description=FastAPI Application
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/bitcos_poc
Environment="PATH=/home/ubuntu/venv/bin"

ExecStart=/home/ubuntu/venv/bin/gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 2 --bind 127.0.0.1:8000

Restart=always

[Install]
WantedBy=multi-user.target

sudo systemctl daemon-reload
sudo systemctl reset-failed fastapi

sudo systemctl start fastapi
sudo systemctl status fastapi



sudo apt update
sudo apt install nginx -y

sudo systemctl status nginx

sudo nano /etc/nginx/sites-available/fastapi

server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket Support for FastAPI
    location /api/ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}


sudo ln -s /etc/nginx/sites-available/fastapi /etc/nginx/sites-enabled/

sudo rm /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl restart nginx
sudo systemctl status nginx

#### daily deployment command ########

cd ~/bitcos_poc

git pull

source ~/venv/bin/activate

pip install -r requirements.txt
sudo systemctl daemon-reload
# gunicorn service
sudo systemctl restart fastapi   
sudo systemctl status fastapi 
# nginx service
sudo nginx -t
sudo systemctl restart nginx


<!-- {
  "broker_name": "Delta Exchange",
  "broker_login_id": "delta01",
  "api_key": "zS1jowZhVOMzQGCUyYvz0iwtfUJY0J",
  "secret_key": "gAAAAABprAiMdhaZ9zoxrusZaSudllzjjXq-v7NueSPXC7LmfhiiwX23nLTyIX8iQDSAAYZjqo8lyL4T2srY0LtB7h9XmWLaaIaak_OGJaZ-Rx_IVPwN-yN_WLgdtVqkT6wEffCxIs-6W0NVAcg6kjxYN20Ir5M4jw==",
  "totp_secret": "m7PCO2FNhg9So8Q6o0JIbG8NhHb7vJ6ICdmKXuewjsacfxgWW36oC0ByvePV",
  "name_tag": "ankit-account",
  "redirect_url": "https://api.india.delta.exchange"
} -->


Delta Exchange API Service Class:

File Path: 
app/services/delta_exchange.py
What changed: Fixes signature generation logic for GET requests with query parameters (prepends ? to the signature payload) and changes the default API base URL to India (api.india.delta.exchange).
Brokers API Endpoints:

File Path: 
app/api/brokers.py
What changed: Cleans/strips whitespaces from API credentials, decodes Fernet-encrypted keys sent from the frontend request payload, implements dual-endpoint check (tests India then Global automatically), and handles IP restriction errors by outputting the specific IP to whitelist.
Trading API Routes & Helper:

File Path: 
app/api/trading.py
What changed: Aligns the default base URL default to the India Exchange in get_delta_api if no broker redirect URL is stored.
Websocket API Routes:

File Path: 
app/api/websocket.py
What changed: Aligns the default base URL default to the India Exchange in the websocket handler if no broker redirect URL is stored.

