resource "digitalocean_droplet" "bot" { name = "trading-bot"; region = var.region; size = var.size; image = var.droplet_image_id; ssh_keys = var.ssh_key_fingerprints; monitoring = true }
