# CONFIG

terraform {
  required_providers {
    yandex = {
      source = "yandex-cloud/yandex"
    }
  }
  required_version = ">= 1.2.0"
}

variable "YC_TOKEN" {
  type      = string
  sensitive = true
}
variable "TELEGRAM_TOKEN" {
  type      = string
  sensitive = true
}
variable "YC_CLOUD_ID" { type = string }
variable "YC_FOLDER_ID" { type = string }
variable "YC_ZONE" { type = string }

provider "yandex" {
  zone      = var.YC_ZONE
  token     = var.YC_TOKEN
  cloud_id  = var.YC_CLOUD_ID
  folder_id = var.YC_FOLDER_ID
}

locals {
  ignore = ["index.zip", ".git", ".vscode", ".terraform", "venv", ".env", "terraform.tfstate", "terraform.tfstate.backup"]
}

# SERVICE ACCOUNT

resource "yandex_iam_service_account" "sa" {
  name        = "recognizer-bot-sa"
  description = ""
  folder_id   = var.YC_FOLDER_ID
}

resource "yandex_resourcemanager_folder_iam_member" "sa-ai-editor" {
  role      = "ai.editor"
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
  folder_id = var.YC_FOLDER_ID
}

resource "yandex_resourcemanager_folder_iam_member" "sa-speechkit-stt-user" {
  role      = "ai.speechkit-stt.user"
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
  folder_id = var.YC_FOLDER_ID
}

resource "yandex_resourcemanager_folder_iam_member" "sa-functions-editor" {
  role      = "functions.editor"
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
  folder_id = var.YC_FOLDER_ID
}

# FUNCTION

data "archive_file" "bundle" {
  type        = "zip"
  output_path = "index.zip"
  source_dir  = "."
  excludes    = local.ignore
}

resource "yandex_function" "recognizer-bot" {
  name               = "recognizer-bot"
  user_hash          = data.archive_file.bundle.output_sha256
  runtime            = "python312"
  entrypoint         = "index.handler"
  memory             = "128"
  execution_timeout  = "120"
  service_account_id = yandex_iam_service_account.sa.id
  environment = {
    TELEGRAM_TOKEN = var.TELEGRAM_TOKEN
  }
  content {
    zip_filename = "index.zip"
  }
}

# GATEWAY

resource "yandex_api_gateway" "gw" {
  name = "gw"
  spec = <<-EOT
    openapi: 3.0.0
    info:
      title: Sample API
      version: 1.0.0

    paths:
      /function:
        post:
          x-yc-apigateway-integration:
            type: cloud_functions
            function_id: ${yandex_function.recognizer-bot.id}
            service_account_id: ${yandex_iam_service_account.sa.id}
          operationId: function
  EOT
}

data "http" "registerGateway" {
  method = "POST"
  url    = "https://api.telegram.org/bot${var.TELEGRAM_TOKEN}/setWebhook"
  request_headers = {
    Content-Type = "application/json"
  }
  request_body = jsonencode({
    url = "${yandex_api_gateway.gw.domain}/function"
  })
  lifecycle {
    postcondition {
      condition     = jsondecode(self.response_body).ok == true
      error_message = "Invalid gateway registration"
    }
  }
}
