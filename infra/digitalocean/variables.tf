variable "region" { type = string }
variable "ssh_key_fingerprints" { type = list(string) }
variable "trusted_ssh_cidrs" { type = list(string) }
variable "droplet_image_id" { type = number }
variable "droplet_image_slug" { type = string; validation { condition = var.droplet_image_slug == "ubuntu-26-04-x64"; error_message = "reviewed slug required" } }
variable "size" { type = string; default = "s-1vcpu-1gb" }
