terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.0.0"
    }
  }
}

variable "project_id" {
  type        = string
  description = "GCP Project ID"
}

variable "region" {
  type        = string
  default     = "us-east4"
  description = "GCP Deployment Region"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Deploy the secure container hosting the ADK 2.0 workflow
resource "google_cloud_run_v2_service" "agent_service" {
  name     = "algebra-socratic-agent"
  location = var.region

  template {
    containers {
      image = "gcr.io/${var.project_id}/algebra-agent-runtime:latest"
      
      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }
    }
  }
}

# Apply Model Armor security policies to clean inputs and outputs
resource "google_gemini_model_armor_policy" "safety_policy" {
  name        = "socratic-safety-gateway"
  project     = var.project_id
  location    = var.region
  description = "Screens out prompt injections and PII from algebra students"

  prompt_shield {
    enable_injection_detection = true
    enable_pii_filtering       = true
  }
}
