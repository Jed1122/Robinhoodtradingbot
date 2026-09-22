resource "digitalocean_firewall" "bot" {
  name = "trading-bot"; droplet_ids = [digitalocean_droplet.bot.id]
  inbound_rule { protocol = "tcp"; port_range = "22"; source_addresses = var.trusted_ssh_cidrs }
  outbound_rule { protocol = "tcp"; port_range = "443"; destination_addresses = ["0.0.0.0/0", "::/0"] }
  outbound_rule { protocol = "udp"; port_range = "53"; destination_addresses = ["0.0.0.0/0", "::/0"] }
  outbound_rule { protocol = "udp"; port_range = "123"; destination_addresses = ["0.0.0.0/0", "::/0"] }
}
