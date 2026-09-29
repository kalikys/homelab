# Kalislav Smirnov, DevOps Engineer

Updated: 2026-09-29 · Website: https://kalik8s.com/ · Russian version: https://kalik8s.com/ru/

DevOps engineer with 4.5 years of experience. I build Kubernetes platforms, GitLab CI/CD pipelines and infrastructure automation with Ansible and Terraform, most recently for banks and government agencies, including fully air-gapped environments. I also integrate SAST, DAST and SCA scanning into pipelines. I live in Tbilisi, Georgia, and I am open to relocation or remote work.

## Hiring details

- Status: open to offers now, can start right away.
- Location: Tbilisi, Georgia.
- Relocation: the EU, the USA or Kazakhstan. Needs visa sponsorship or another work permit; no right to work outside Georgia yet.
- Remote: open to remote work for a company in any country.
- Employment: full-time as an employee, B2B or contract.
- Best fit: DevOps and platform engineering roles (Kubernetes, GitLab CI/CD, Ansible, Terraform, security checks in pipelines), especially in banking, fintech and government projects.
- Languages: English (B2), Russian.
- Book a 20-minute intro call: https://cal.com/kalikys/intro
- Contact: kalikys@outlook.com · Telegram @kalikys · LinkedIn https://www.linkedin.com/in/devops-kalislav-smirnov/ · GitHub https://github.com/kalikys

## Impact

- Edge device (mini-PC) infrastructure setup: 10 hours → 20 minutes.
- 5 end-to-end DevSecOps platform implementations for banking and government clients.
- Multi-datacenter Kubernetes platforms with 100+ VMs and disaster recovery protocols.
- Release cycle for 20+ microservices: 2 weeks → 3 days.

## Case studies

Client names are left out on purpose.

### 1. Secure development process across a federal company

Federal company with 90+ development teams and 200+ software products. Team of 3 engineers, 1 year.

- Deployed OSA Firewall and put it into the package supply chain, so open source dependencies are checked before developers get them.
- Deployed an ASOC platform that collects findings from every scanner in one place.
- Added Gitleaks, Trivy, SCA and OSA checks to the shared GitLab CI templates.
- Trained DevOps engineers and developers to work with the findings; prepared and agreed 30+ process documents and instructions with the client.
- Result: security checks run in 100% of pipelines.
- Stack: GitLab CI, OSA Firewall, ASOC, Gitleaks, Trivy, SCA.
- Press release (Russian): https://habr.com/ru/companies/swordfish_security/news/1064506/

### 2. Signed package delivery into a bank's air-gapped network

- Built a secure, GPG-signed package delivery service in Python on Kubernetes for a major bank's air-gapped Nexus repository.
- Every package is signed with GPG, and the signature is checked before it lands in Nexus.
- Stack: Python, Kubernetes, GPG, Nexus.

### 3. Edge mini-PC setup automated end to end (investment bank)

- Automated the entire infrastructure deployment for edge devices with Ansible and custom scripts.
- Result: setup time per device cut from 10 hours to 20 minutes.
- Stack: Ansible, Bash, Linux.

### 4. From a monolith to 10 services on Kubernetes (investment bank)

- Designed and ran the initial migration of a core monolithic application to 10 containerized microservices on Kubernetes.
- Wrote Helm charts for all 10 services: one-command deployments and rollbacks.
- Built an observability stack from scratch with Prometheus, Grafana and ELK.
- Stack: Kubernetes, Helm, Prometheus, Grafana, ELK.

## Experience

### DevSecOps Engineer, Swordfish Security (Feb 2025 - Aug 2026, full-time)

Deploying and maintaining DevSecOps platforms for enterprise clients in banking, fintech, and government sectors, including fully air-gapped environments.

- Led 5 end-to-end DevSecOps platform implementations for banking and government clients, from architecture design to final handover.
- Engineered and deployed a secure, GPG-signed package delivery service using Python and Kubernetes for a major bank's air-gapped Nexus repository.
- Automated the integration of SAST, DAST, and SCA tools (Semgrep, Trivy) into GitLab CI, enabling security scans on 100% of new code commits.
- Developed a suite of 15+ reusable Ansible roles to standardize deployments across client environments, reducing setup time for new projects by an estimated 30%.
- Designed and managed multi-datacenter Kubernetes platforms (100+ VMs) with disaster recovery protocols for high-availability financial systems.
- Prepared and conducted product demonstrations and acceptance testing (Nexus, GitLab, DevSecOps products).
- Maintained internal infrastructure: GitLab, proprietary products, RnD and PROD environments

### DevOps Engineer, Sinara Investment Bank (Oct 2024 - Feb 2025)

- Automated the entire infrastructure deployment process for edge devices (mini-PCs), slashing setup time from 10 hours to 20 minutes using Ansible and custom scripts.
- Architected and executed the initial migration of a core monolithic application to 10 containerized microservices on Kubernetes.
- Built a complete observability stack from scratch using Prometheus, Grafana, and ELK, providing real-time monitoring and alerting for the new microservices architecture.
- Developed and managed Helm charts for all 10 services, enabling one-command deployments and rollbacks.

### DevOps Engineer, Engineering & Manufacturing Company (Apr 2022 - Oct 2024)

- Overhauled the CI/CD process by implementing automated testing and deployment pipelines in GitLab CI, cutting the release cycle for 20+ microservices from 2 weeks to 3 days.
- Automated manual deployment checklists with Ansible and Bash scripts, reducing hands-on deployment time from over 4 hours to under 30 minutes per release.
- Led the containerization of 20+ legacy Java microservices using Docker, standardizing environments and eliminating configuration drift between staging and production.
- Managed and maintained the company's production infrastructure, consisting of 50+ Linux servers across two data centers.

## Skills

- Platform: Kubernetes, Helm, Docker, Linux, microservices, disaster recovery
- Automation & IaC: Ansible, Terraform, Python, Bash, OOP
- CI/CD: GitLab CI, Jenkins, Nexus, Git, acceptance testing
- Security: SAST, DAST, SCA, Semgrep, Trivy, AppScreener, AppSec.Hub, AppSec.Track, GPG, OSA Firewall
- Observability: Prometheus, Grafana, Alertmanager, ELK
- Data & messaging: PostgreSQL, ClickHouse, RabbitMQ, Airflow

## Learning

- Preparing for Kubernetes certifications: CKA first, then CKAD. Started in 2026.

## Education

- Master of Engineering, Aerospace, Aeronautical and Astronautical Engineering. Bauman Moscow State Technical University, 2020 - 2026.

## Home lab

This site runs on a Proxmox VE mini-PC at home, managed with Terraform (https://github.com/kalikys/homelab). No open ports: the site is published through Cloudflare Tunnel, and the page includes a public sandbox shell in an isolated, throwaway VM (https://shell.kalik8s.com).
