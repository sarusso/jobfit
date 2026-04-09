import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from ...models import User, Profile, LLMPricing, Company, Job, CV, Score

DEMO_USERNAME  = 'aB3kXm9pQr7nYw2vLs'   # fixed 18-char slug, same format as random_username()
DEMO_EMAIL     = 'demo@jobfit.fyi'
ADMIN_USERNAME = 'admin'
ADMIN_EMAIL    = 'admin@jobfit.fyi'
ADMIN_PASSWORD = 'admin'


# ---------------------------------------------------------------------------
# Demo CV content
# ---------------------------------------------------------------------------

CV_DATA = {
    'name': 'Alex Morgan',
    'title': 'Senior Software Engineer',
    'email': 'alex.morgan@example.com',
    'phone': '+44 7700 900123',
    'location': 'London, UK',
    'summary': (
        'Senior Software Engineer with 8 years of experience building scalable '
        'backend systems and cloud infrastructure. Specialises in Python, distributed '
        'systems, and AWS. Proven track record of leading teams and delivering '
        'high-impact platform work at both startups and consultancies.'
    ),
    'skills': [
        'Python (Django, FastAPI, Celery)',
        'AWS (EKS, Lambda, RDS, S3, CloudFormation)',
        'Kubernetes & Docker',
        'PostgreSQL, Redis',
        'Terraform & CI/CD (GitHub Actions, ArgoCD)',
        'REST APIs & event-driven architectures (Kafka)',
        'Data pipelines (Airflow, dbt)',
        'Team leadership & mentoring',
    ],
    'experience': [
        {
            'title': 'Lead Engineer',
            'company': 'DataPipe Ltd',
            'period': '2020 – present',
            'bullets': [
                'Designed and built a real-time ML feature store serving 50M+ events/day on AWS EKS.',
                'Led a team of 6 engineers; introduced ADRs, on-call runbooks, and reduced MTTR by 40%.',
                'Migrated monolithic Django app to microservices, cutting deployment time from 2h to 8min.',
                'Built self-serve data pipeline platform using Airflow and dbt; onboarded 12 internal teams.',
            ],
        },
        {
            'title': 'Senior Software Engineer',
            'company': 'TechConsult',
            'period': '2017 – 2020',
            'bullets': [
                'Delivered cloud migration (on-prem → AWS) for a FTSE 250 retail client; saved £2M/year.',
                'Built FastAPI-based API gateway handling 10k req/s with <20ms p99 latency.',
                'Implemented Kubernetes-based blue/green deployment pipeline with zero-downtime releases.',
                'Mentored 4 junior engineers; introduced code review practices and TDD.',
            ],
        },
        {
            'title': 'Software Engineer',
            'company': 'Startly',
            'period': '2016 – 2017',
            'bullets': [
                'Full-stack development with Django and React; built core SaaS billing module.',
                'Integrated Stripe API and automated invoicing, reducing finance team overhead by 60%.',
            ],
        },
    ],
    'education': [
        ('MSc Computer Science', 'Imperial College London', '2016'),
        ('BSc Mathematics & Computing', 'University of Bristol', '2014'),
    ],
}


def _build_cv_pdf(path: Path):
    from fpdf import FPDF

    def s(text):
        """Sanitize text to latin-1 safe characters."""
        return (text
                .replace('\u2014', ' - ')   # em dash
                .replace('\u2013', '-')      # en dash
                .replace('\u2022', '-')      # bullet
                .replace('\u2019', "'")      # right single quote
                .replace('\u2018', "'")      # left single quote
                .replace('\u201c', '"')      # left double quote
                .replace('\u201d', '"')      # right double quote
                .replace('\u2192', '->')     # right arrow
                .replace('\u2190', '<-'))    # left arrow

    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    w = pdf.w - 40  # usable width

    # Name & title
    pdf.set_font('Helvetica', 'B', 22)
    pdf.cell(w, 10, s(CV_DATA['name']), ln=True)
    pdf.set_font('Helvetica', '', 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(w, 6, s(CV_DATA['title']), ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Helvetica', '', 9)
    pdf.cell(w, 5, s(f"{CV_DATA['email']}  |  {CV_DATA['phone']}  |  {CV_DATA['location']}"), ln=True)
    pdf.ln(3)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
    pdf.ln(4)

    def section(title):
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(30, 80, 160)
        pdf.cell(w, 7, s(title.upper()), ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.line(20, pdf.get_y(), pdf.w - 20, pdf.get_y())
        pdf.ln(2)

    # Summary
    section('Summary')
    pdf.set_font('Helvetica', '', 10)
    pdf.multi_cell(w, 5, s(CV_DATA['summary']))
    pdf.ln(3)

    # Skills
    section('Technical Skills')
    pdf.set_font('Helvetica', '', 10)
    for i, skill in enumerate(CV_DATA['skills']):
        pdf.cell(w / 2, 5, s('- ' + skill), ln=(i % 2 == 1))
    if len(CV_DATA['skills']) % 2:
        pdf.ln()
    pdf.ln(3)

    # Experience
    section('Experience')
    for exp in CV_DATA['experience']:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(w * 0.7, 6, s(f"{exp['title']}  -  {exp['company']}"))
        pdf.set_font('Helvetica', 'I', 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(w * 0.3, 6, s(exp['period']), align='R', ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Helvetica', '', 9)
        for b in exp['bullets']:
            pdf.set_x(pdf.l_margin)
            pdf.cell(6, 4.5, '')
            pdf.multi_cell(w - 6, 4.5, s('- ' + b))
        pdf.ln(2)

    # Education
    section('Education')
    pdf.set_font('Helvetica', '', 10)
    for degree, school, year in CV_DATA['education']:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(w * 0.7, 6, s(f"{degree}  -  {school}"))
        pdf.set_font('Helvetica', 'I', 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(w * 0.3, 6, s(year), align='R', ln=True)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


# ---------------------------------------------------------------------------
# Demo companies / jobs
# ---------------------------------------------------------------------------

COMPANIES = [
    {
        'slug': 'acme-ai',
        'name': 'Acme AI',
        'description': (
            'Acme AI is an early-stage startup building foundation models and '
            'ML infrastructure for enterprise customers. Series B, 80 people, '
            'fully remote.'
        ),
        'jobs': [
            {
                'title': 'Senior ML Engineer',
                'location': 'Remote',
                'employment_type': 'full-time',
                'experience_level': 'senior',
                'salary': '$140,000 – $180,000 a year',
                'summary': (
                    'Join our ML platform team to build the infrastructure that trains '
                    'and serves our foundation models at scale.'
                ),
                'description': (
                    'We are looking for a Senior ML Engineer to own the design and '
                    'operation of our model training and serving infrastructure. You '
                    'will work closely with research scientists to productionise '
                    'experiments and ensure models run reliably at scale. This is a '
                    'high-ownership role with direct impact on the company\'s core product.'
                ),
                'responsibilities': [
                    'Design and maintain distributed training pipelines on AWS EKS',
                    'Build and operate model serving infrastructure (latency, throughput, cost)',
                    'Partner with research to accelerate experiment iteration cycles',
                    'Own observability and on-call for ML infrastructure',
                    'Mentor junior engineers and contribute to architecture decisions',
                ],
                'requirements': [
                    '5+ years of software engineering experience',
                    'Strong Python skills; experience with PyTorch or JAX',
                    'Deep understanding of AWS (EKS, S3, EC2, Lambda)',
                    'Experience with distributed systems and data pipelines',
                    'Comfortable operating Kubernetes clusters in production',
                ],
                'nice_to_have': [
                    'Experience with LLM training or fine-tuning',
                    'Familiarity with Airflow, Ray, or similar orchestration',
                    'Published research or open-source contributions in ML',
                ],
                'source': 'https://jobs.acme-ai.example.com/senior-ml-engineer',
            },
            {
                'title': 'Python Platform Engineer',
                'location': 'Remote',
                'employment_type': 'full-time',
                'experience_level': 'mid',
                'salary': '$120,000 – $150,000 a year',
                'summary': (
                    'Build the internal developer platform that keeps 80 engineers '
                    'shipping fast and safely.'
                ),
                'description': (
                    'As a Python Platform Engineer you will own the developer tooling, '
                    'CI/CD pipelines, and shared libraries used across all of Acme AI\'s '
                    'Python services. You care deeply about developer experience and '
                    'will work autonomously to reduce friction for the whole engineering org.'
                ),
                'responsibilities': [
                    'Own and evolve our Python monorepo tooling and shared libraries',
                    'Build and maintain CI/CD pipelines (GitHub Actions, ArgoCD)',
                    'Drive adoption of testing standards and code quality tooling',
                    'Maintain internal PyPI registry and dependency management',
                    'Collaborate with security to enforce supply-chain policies',
                ],
                'requirements': [
                    '3+ years Python engineering experience',
                    'Experience building or maintaining CI/CD pipelines',
                    'Comfortable with Docker and Kubernetes',
                    'Strong understanding of Python packaging and dependency management',
                ],
                'nice_to_have': [
                    'Experience with Bazel or similar build systems',
                    'Contributions to open-source Python tooling',
                    'Familiarity with Nix or reproducible builds',
                ],
                'source': 'https://jobs.acme-ai.example.com/python-platform-engineer',
            },
        ],
    },
    {
        'slug': 'cloudco',
        'name': 'CloudCo',
        'description': (
            'CloudCo provides managed cloud infrastructure and platform services to '
            'mid-market enterprises across Europe and North America. 350 employees, '
            'Series D.'
        ),
        'jobs': [
            {
                'title': 'Cloud Platform Lead',
                'location': 'London',
                'employment_type': 'full-time',
                'experience_level': 'senior',
                'salary': '£90,000 – £120,000 a year',
                'summary': (
                    'Lead a team of 5 engineers building and operating the core '
                    'Kubernetes platform used by all CloudCo customers.'
                ),
                'description': (
                    'The Cloud Platform Lead will own our multi-tenant Kubernetes '
                    'platform from architecture through to day-2 operations. You will '
                    'lead a team of 5 platform engineers, work with customers on '
                    'complex requirements, and define the technical roadmap for the '
                    'next 18 months.'
                ),
                'responsibilities': [
                    'Lead technical direction for the Kubernetes platform team',
                    'Architect multi-tenant clusters with security and isolation in mind',
                    'Own SLAs and on-call rotation for platform infrastructure',
                    'Work directly with enterprise customers on platform requirements',
                    'Recruit, mentor, and grow the platform engineering team',
                ],
                'requirements': [
                    '6+ years of engineering experience, 2+ in a tech lead role',
                    'Deep Kubernetes expertise (CKA/CKAD preferred)',
                    'Experience with Terraform and infrastructure-as-code',
                    'Strong AWS knowledge (EKS, IAM, VPC, networking)',
                    'Excellent communication skills for customer-facing work',
                ],
                'nice_to_have': [
                    'Experience with multi-cloud (AWS + GCP or Azure)',
                    'Background in managed services or SaaS platform engineering',
                    'Familiarity with eBPF-based networking (Cilium, Calico)',
                ],
                'source': 'https://careers.cloudco.example.com/cloud-platform-lead',
            },
            {
                'title': 'DevOps Engineer',
                'location': 'Remote',
                'employment_type': 'full-time',
                'experience_level': 'mid',
                'salary': '£70,000 – £90,000 a year',
                'summary': (
                    'Join the SRE team to build and automate the deployment and '
                    'monitoring of CloudCo\'s core services.'
                ),
                'description': (
                    'As a DevOps Engineer you will work within the SRE team to '
                    'improve deployment automation, observability, and reliability '
                    'for CloudCo\'s internal and customer-facing services. You will '
                    'be on the on-call rotation and will drive incident post-mortems.'
                ),
                'responsibilities': [
                    'Maintain and improve CI/CD pipelines across 30+ services',
                    'Build and operate monitoring and alerting (Prometheus, Grafana)',
                    'Participate in on-call rotation and own post-mortem process',
                    'Automate toil using Python and Bash scripting',
                    'Collaborate with dev teams to improve deployment safety',
                ],
                'requirements': [
                    '3+ years in a DevOps or SRE role',
                    'Strong scripting skills (Python or Bash)',
                    'Experience with Prometheus, Grafana, or similar observability stack',
                    'Comfortable with Linux systems administration',
                    'Experience with at least one major cloud provider',
                ],
                'nice_to_have': [
                    'Experience with Ansible or configuration management',
                    'Familiarity with chaos engineering principles',
                ],
                'source': 'https://careers.cloudco.example.com/devops-engineer',
            },
            {
                'title': 'Backend Engineer',
                'location': 'New York, NY',
                'employment_type': 'full-time',
                'experience_level': 'mid',
                'salary': '$130,000 – $160,000 a year',
                'summary': (
                    'Build the APIs and backend services that power the CloudCo '
                    'customer portal and partner integrations.'
                ),
                'description': (
                    'CloudCo is looking for a Backend Engineer to join the product '
                    'engineering team building our customer portal and public APIs. '
                    'You will design and ship features end-to-end, from data model '
                    'to REST endpoint, and collaborate closely with our NYC-based '
                    'product and design teams.'
                ),
                'responsibilities': [
                    'Design and implement REST APIs consumed by web and mobile clients',
                    'Own the data model and database performance for your domain',
                    'Write high-quality, well-tested Python (Django/FastAPI)',
                    'Participate in design reviews and contribute to technical standards',
                    'Work in a fast-paced agile environment with bi-weekly releases',
                ],
                'requirements': [
                    '3+ years backend engineering experience',
                    'Strong Python skills with Django or FastAPI',
                    'Experience designing relational database schemas (PostgreSQL)',
                    'Familiarity with REST API best practices',
                    'Comfortable in an agile, product-led environment',
                ],
                'nice_to_have': [
                    'GraphQL API experience',
                    'Exposure to event-driven architecture (Kafka, SQS)',
                ],
                'source': 'text',
                'archived': True,
            },
        ],
    },
    {
        'slug': 'datasystems',
        'name': 'DataSystems',
        'description': (
            'DataSystems is a data engineering consultancy helping data-intensive '
            'companies build reliable, scalable data platforms. 120 people across '
            'London, Amsterdam, and Berlin.'
        ),
        'jobs': [
            {
                'title': 'Data Platform Engineer',
                'location': 'Remote',
                'employment_type': 'full-time',
                'experience_level': 'senior',
                'salary': '$130,000 – $160,000 a year',
                'summary': (
                    'Own the design and evolution of client data platforms built on '
                    'modern open-source tooling.'
                ),
                'description': (
                    'As a Data Platform Engineer at DataSystems, you will be '
                    'embedded with client teams to design, build, and hand over '
                    'production-grade data platforms. You are comfortable working '
                    'across the stack -from pipeline orchestration to cloud '
                    'infrastructure -and can communicate complex technical concepts '
                    'to non-technical stakeholders.'
                ),
                'responsibilities': [
                    'Design data platform architectures using dbt, Airflow, and Spark',
                    'Implement and operate data pipelines on AWS or GCP',
                    'Work directly with client engineering and analytics teams',
                    'Write platform-as-code (Terraform) for reproducible environments',
                    'Conduct architecture reviews and produce technical documentation',
                ],
                'requirements': [
                    '5+ years of data or software engineering experience',
                    'Strong Python skills and experience with Airflow or Prefect',
                    'Hands-on experience with dbt and a modern data warehouse',
                    'Cloud infrastructure experience (AWS or GCP)',
                    'Excellent written and verbal communication for client-facing work',
                ],
                'nice_to_have': [
                    'Experience with Apache Spark or Flink',
                    'Exposure to streaming data (Kafka, Kinesis)',
                    'Prior consulting or client-services background',
                ],
                'source': 'https://datasystems.example.com/jobs/data-platform-engineer',
            },
            {
                'title': 'Analytics Engineer',
                'location': 'London',
                'employment_type': 'full-time',
                'experience_level': 'mid',
                'salary': '£65,000 – £85,000 a year',
                'summary': (
                    'Bridge the gap between data engineering and analytics -build '
                    'clean, trusted datasets that power business decisions.'
                ),
                'description': (
                    'The Analytics Engineer will work within our London delivery '
                    'team, building dbt models, semantic layers, and dashboards for '
                    'clients across fintech, retail, and logistics. You care about '
                    'data quality, documentation, and making data accessible to '
                    'non-technical users.'
                ),
                'responsibilities': [
                    'Build and maintain dbt projects: models, tests, and documentation',
                    'Design semantic layers (Looker, Metabase, or similar)',
                    'Work with client analysts to understand and model their data domains',
                    'Champion data quality through automated testing and monitoring',
                    'Contribute to internal analytics engineering standards',
                ],
                'requirements': [
                    '2+ years working with dbt in a production environment',
                    'Strong SQL skills across multiple dialects',
                    'Experience with at least one BI tool (Looker, Tableau, Metabase)',
                    'Python scripting for data tasks',
                    'Good communication skills for working with non-technical stakeholders',
                ],
                'nice_to_have': [
                    'Experience with Snowflake, BigQuery, or Databricks',
                    'Familiarity with data contracts or data mesh principles',
                ],
                'source': 'text',
            },
        ],
    },
    {
        'slug': 'retailcorp',
        'name': 'RetailCorp',
        'archived': True,
        'description': (
            'RetailCorp is a large UK retail chain with 500+ stores, undergoing a '
            'digital transformation. 5,000 employees. The engineering team is small '
            'relative to the business and works primarily with legacy Java systems.'
        ),
        'jobs': [
            {
                'title': 'Java Backend Developer',
                'location': 'Manchester',
                'employment_type': 'full-time',
                'experience_level': 'mid',
                'salary': '£45,000 – £60,000 a year',
                'summary': (
                    'Maintain and extend our core inventory and order management '
                    'systems built on Java and Oracle.'
                ),
                'description': (
                    'RetailCorp is looking for a Java Backend Developer to join the '
                    'central engineering team. You will maintain and extend the legacy '
                    'inventory and order management systems that power our 500+ stores. '
                    'The role is primarily in Java 8/11 with Oracle databases and '
                    'on-premise infrastructure.'
                ),
                'responsibilities': [
                    'Maintain and extend Java-based inventory and OMS systems',
                    'Write and debug PL/SQL stored procedures in Oracle',
                    'Integrate with third-party logistics and ERP systems',
                    'Participate in a weekly on-call rota',
                    'Document changes and produce test plans for QA',
                ],
                'requirements': [
                    '3+ years Java development experience (Java 8 or 11)',
                    'Experience with Oracle databases and PL/SQL',
                    'Understanding of enterprise integration patterns (ESB, MQ)',
                    'Familiarity with on-premise deployment and release management',
                    'Strong debugging and legacy-code comprehension skills',
                ],
                'nice_to_have': [
                    'Retail or supply-chain domain experience',
                    'Exposure to SAP or similar ERP systems',
                ],
                'source': 'text',
            },
            {
                'title': 'IT Project Manager',
                'location': 'Manchester',
                'employment_type': 'full-time',
                'experience_level': 'mid',
                'salary': '£50,000 – £65,000 a year',
                'summary': (
                    'Lead delivery of IT projects across our store operations and '
                    'back-office systems.'
                ),
                'description': (
                    'The IT Project Manager will manage end-to-end delivery of '
                    'technology projects across RetailCorp\'s store estate and '
                    'head office systems. You will coordinate vendors, internal '
                    'stakeholders, and the IT team to deliver on time and within budget. '
                    'This is a largely non-technical, delivery-focused role.'
                ),
                'responsibilities': [
                    'Own project plans, budgets, and status reporting for IT initiatives',
                    'Coordinate third-party vendors and internal delivery teams',
                    'Run steering committee meetings and produce board-level updates',
                    'Manage risks, issues, and dependencies across concurrent projects',
                    'Drive change management and business readiness activities',
                ],
                'requirements': [
                    '3+ years IT project management experience',
                    'PRINCE2 or PMP certification',
                    'Experience managing third-party vendors and contracts',
                    'Strong stakeholder management and communication skills',
                    'Proficiency with MS Project or similar PM tooling',
                ],
                'nice_to_have': [
                    'Retail or FMCG industry experience',
                    'Familiarity with ITIL or service management frameworks',
                ],
                'source': 'text',
            },
        ],
    },
    {
        'slug': 'fintechltd',
        'name': 'FinTech Ltd',
        'description': (
            'FinTech Ltd builds payment infrastructure and embedded finance APIs '
            'for banks and neobanks across Europe. Regulated, 200 employees, '
            'profitable and growing.'
        ),
        'jobs': [
            {
                'title': 'Senior Backend Engineer',
                'location': 'London',
                'employment_type': 'full-time',
                'experience_level': 'senior',
                'salary': '£95,000 – £125,000 a year',
                'summary': (
                    'Design and build the payment processing APIs used by 40+ '
                    'banking clients across Europe.'
                ),
                'description': (
                    'FinTech Ltd is looking for a Senior Backend Engineer to join '
                    'the core payments team. You will own critical services that '
                    'process millions of transactions daily, work within a regulated '
                    'environment, and collaborate with compliance and security teams '
                    'to maintain our FCA authorisation.'
                ),
                'responsibilities': [
                    'Design and build high-availability payment processing services',
                    'Own API contracts with banking clients; maintain backwards compatibility',
                    'Ensure services meet PCI-DSS and FCA compliance requirements',
                    'Conduct thorough code reviews with a security-first mindset',
                    'On-call for payment-critical infrastructure',
                ],
                'requirements': [
                    '5+ years backend engineering experience',
                    'Python expertise (Django or FastAPI preferred)',
                    'Experience with PostgreSQL and high-throughput workloads',
                    'Strong understanding of security and data privacy principles',
                    'Comfort working in regulated, compliance-heavy environments',
                ],
                'nice_to_have': [
                    'Experience in payments, banking, or fintech',
                    'Knowledge of ISO 20022 or open banking standards',
                    'Familiarity with event sourcing or CQRS patterns',
                ],
                'source': 'https://fintechltd.example.com/careers/senior-backend-engineer',
            },
            {
                'title': 'API Platform Engineer',
                'location': 'Remote',
                'employment_type': 'full-time',
                'experience_level': 'mid',
                'salary': '£75,000 – £95,000 a year',
                'summary': (
                    'Own the developer platform and API gateway that our banking '
                    'clients use to integrate with FinTech Ltd\'s services.'
                ),
                'description': (
                    'As API Platform Engineer you will build and operate the '
                    'developer-facing infrastructure: API gateway, client SDKs, '
                    'sandbox environments, and the developer portal. You will work '
                    'closely with client integration teams and own the experience '
                    'from sign-up to production go-live.'
                ),
                'responsibilities': [
                    'Build and maintain the API gateway (rate limiting, auth, routing)',
                    'Own sandbox environments used by clients during integration',
                    'Develop and maintain Python and TypeScript client SDKs',
                    'Write and maintain developer documentation and integration guides',
                    'Monitor and improve API reliability and performance',
                ],
                'requirements': [
                    '3+ years building or operating APIs at scale',
                    'Strong Python skills; TypeScript a plus',
                    'Experience with API gateways (Kong, AWS API Gateway, or similar)',
                    'Good understanding of OAuth2 and API security patterns',
                    'Empathy for developer experience; experience writing SDK or docs',
                ],
                'nice_to_have': [
                    'Experience building developer portals',
                    'Background in fintech or financial services APIs',
                ],
                'source': 'text',
            },
            {
                'title': 'Principal Engineer',
                'location': 'London',
                'employment_type': 'full-time',
                'experience_level': 'senior',
                'salary': '£120,000 – £150,000 a year',
                'summary': (
                    'Shape the technical direction of FinTech Ltd as we scale '
                    'from 40 to 100 engineers over the next two years.'
                ),
                'description': (
                    'The Principal Engineer is a senior individual contributor role '
                    'with company-wide technical influence. You will set architecture '
                    'standards, lead major cross-team initiatives, and act as a '
                    'technical advisor to engineering leadership. Deep expertise in '
                    'distributed systems and an ability to navigate regulatory '
                    'complexity are essential.'
                ),
                'responsibilities': [
                    'Define and evolve FinTech Ltd\'s technical architecture standards',
                    'Lead cross-team initiatives (e.g. platform migration, new product lines)',
                    'Act as technical reviewer for high-stakes design decisions',
                    'Work with the CTO to define the engineering roadmap',
                    'Represent engineering in regulatory and compliance discussions',
                ],
                'requirements': [
                    '10+ years of engineering experience, 3+ as staff/principal',
                    'Track record of defining architecture across multiple teams',
                    'Deep expertise in distributed systems and API design',
                    'Experience in a regulated industry (fintech, health, or similar)',
                    'Strong written communication; ability to influence without authority',
                ],
                'nice_to_have': [
                    'Experience scaling an engineering org through hypergrowth',
                    'Background in payments or open banking',
                    'Public speaking or published writing on technical topics',
                ],
                'source': 'text',
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Demo scores (normal + brutal) for 5 jobs
# Key: (company_slug, job_title)
# ---------------------------------------------------------------------------

SCORES = {
    ('acme-ai', 'Senior ML Engineer'): {
        'normal': {
            'score': 8,
            'reasoning': (
                'Strong Python and AWS background maps well to the ML infrastructure '
                'requirements. Experience building data pipelines at DataPipe is directly '
                'relevant. Missing hands-on ML research or PyTorch experience, but the '
                'infrastructure depth more than compensates.'
            ),
            'strengths': [
                'Deep AWS (EKS, Lambda, RDS) expertise exactly matching job requirements',
                'Real-world distributed data pipeline experience (Airflow, Kafka)',
                'Proven team leadership and on-call ownership at DataPipe',
                'Strong Python across multiple frameworks (Django, FastAPI, Celery)',
            ],
            'gaps': [
                'No explicit mention of PyTorch or JAX experience',
                'ML research background not evident from CV',
            ],
        },
        'brutal': {
            'score': 6,
            'reasoning': (
                'Solid platform engineer profile but this role calls for ML infrastructure '
                'depth -training loops, GPU cluster management, model serving latency -'
                'that is not evidenced in the CV. The data pipeline work is adjacent but '
                'not equivalent. Would need significant upskilling on the ML side.'
            ),
            'strengths': [
                'AWS and Kubernetes depth is genuinely strong',
                'Pipeline and orchestration experience transfers partially',
            ],
            'gaps': [
                'No ML framework experience (PyTorch, JAX, TensorFlow)',
                'No evidence of GPU infrastructure or model training work',
                'Feature store work is mentioned but ML serving specifics are absent',
            ],
        },
    },
    ('acme-ai', 'Python Platform Engineer'): {
        'normal': {
            'score': 9,
            'reasoning': (
                'Near-perfect match. The candidate has built exactly this kind of '
                'internal developer platform at DataPipe -Python monorepo tooling, '
                'CI/CD pipelines, Kubernetes, shared libraries. Strong autonomy '
                'indicators and direct evidence of improving developer experience.'
            ),
            'strengths': [
                'Led migration from monolith to microservices -directly relevant',
                'CI/CD ownership (GitHub Actions, ArgoCD) explicitly listed',
                'Kubernetes and Docker production experience',
                'Strong Python packaging and library development background',
                'Demonstrated autonomy and ownership in previous roles',
            ],
            'gaps': [
                'No mention of internal PyPI registry experience',
            ],
        },
        'brutal': {
            'score': 7,
            'reasoning': (
                'Very strong candidate for this level. The CI/CD and platform work '
                'is directly evidenced. Small deductions for no explicit mention of '
                'monorepo tooling (Bazel, pants) or supply-chain security -both '
                'called out in the JD. At mid-level the bar is lower than senior '
                'so this is a competitive application.'
            ),
            'strengths': [
                'CI/CD and developer tooling experience clearly demonstrated',
                'Kubernetes and Docker depth confirmed',
            ],
            'gaps': [
                'Monorepo build system experience (Bazel) not evidenced',
                'Supply-chain security work not mentioned',
            ],
        },
    },
    ('cloudco', 'Cloud Platform Lead'): {
        'normal': {
            'score': 7,
            'reasoning': (
                'Good match on the technical side -Kubernetes, Terraform, AWS, team '
                'leadership all present. The customer-facing aspect is less evidenced; '
                'previous roles were internal-facing. Leadership experience at DataPipe '
                'covers the team-lead requirement.'
            ),
            'strengths': [
                'Kubernetes production expertise (EKS, multi-tenant patterns)',
                'Terraform and IaC experience',
                'Team leadership of 6 engineers demonstrated',
                'AWS networking and IAM depth from EKS work',
            ],
            'gaps': [
                'No explicit customer-facing or enterprise client experience',
                'CKA/CKAD certification not mentioned',
                'SRE/SLA ownership less prominent than pure platform work',
            ],
        },
        'brutal': {
            'score': 5,
            'reasoning': (
                'The technical fundamentals are there but this is a lead role at a '
                'managed-services company -the customer-facing, SLA-accountable '
                'dimension is central to the job and is not evidenced in the CV. '
                'Leadership experience exists but is from a startup context; '
                'enterprise client management is a distinct skill set.'
            ),
            'strengths': [
                'Kubernetes depth is real and relevant',
                'Has led a team, not just contributed individually',
            ],
            'gaps': [
                'Zero customer-facing or enterprise client work on record',
                'No mention of SLA ownership or managed-service context',
                'No certification evidence',
            ],
        },
    },
    ('datasystems', 'Data Platform Engineer'): {
        'normal': {
            'score': 7,
            'reasoning': (
                'Strong overlap: Airflow, dbt, AWS, Python, and Terraform all present. '
                'The consultancy dimension (client-facing, documentation, handover) is '
                'less directly evidenced but previous client delivery at TechConsult '
                'suggests the transferable skills are there.'
            ),
            'strengths': [
                'Airflow and dbt production experience listed explicitly',
                'AWS infrastructure (Terraform, EKS) matches requirements',
                'Strong Python data pipeline background from DataPipe',
                'TechConsult role shows client-delivery capability',
            ],
            'gaps': [
                'No mention of Spark or streaming (Kafka experience is pipeline, not analytics)',
                'Consulting/handover communication less evidenced than technical depth',
            ],
        },
        'brutal': {
            'score': 5,
            'reasoning': (
                'Technical stack is a solid fit but DataSystems is a consultancy -'
                'the ability to own client relationships, manage expectations, and '
                'produce deliverable documentation is as important as coding skill. '
                'The CV reads as a product-engineer profile, not a consultant. '
                'The TechConsult stint is relevant but brief and lacks detail.'
            ),
            'strengths': [
                'dbt and Airflow experience is genuine',
                'Terraform and cloud infrastructure depth confirmed',
            ],
            'gaps': [
                'Consulting soft skills and client management not evidenced in depth',
                'No Spark experience despite it being a requirement',
                'TechConsult detail is thin -hard to assess client-facing capability',
            ],
        },
    },
    ('retailcorp', 'Java Backend Developer'): {
        'normal': {
            'score': 3,
            'reasoning': (
                'The candidate is a Python/cloud specialist with no Java experience '
                'evidenced anywhere in the CV. The role is squarely in Java 8/11 and '
                'Oracle on-premise — a fundamentally different stack. The engineering '
                'depth is there but is not transferable without significant retraining.'
            ),
            'strengths': [
                'General backend engineering fundamentals transfer to some degree',
                'Experience with relational databases (PostgreSQL) partially relevant',
            ],
            'gaps': [
                'No Java experience of any kind evidenced',
                'No Oracle or PL/SQL experience',
                'No on-premise or legacy systems background',
                'Enterprise integration (ESB, MQ) not mentioned',
                'Retail or supply-chain domain knowledge absent',
            ],
        },
        'brutal': {
            'score': 1,
            'reasoning': (
                'Wrong stack entirely. This is a Java/Oracle role; the candidate is '
                'Python/AWS. There is no overlap in the primary technical requirements. '
                'Applying would be wasting both parties\' time.'
            ),
            'strengths': [
                'Strong engineer in general — but in the wrong language and paradigm',
            ],
            'gaps': [
                'Java: not present',
                'Oracle/PL/SQL: not present',
                'On-premise legacy systems: not present',
                'Domain knowledge: not present',
            ],
        },
    },
    ('retailcorp', 'IT Project Manager'): {
        'normal': {
            'score': 2,
            'reasoning': (
                'This is a non-technical delivery and project management role. The '
                'candidate has no PM certifications, no vendor management experience, '
                'and no evidence of running steering committees or board reporting. '
                'The engineering background is a poor fit for what is essentially a '
                'business-facing programme manager position.'
            ),
            'strengths': [
                'Has coordinated cross-team work in an engineering context',
                'Led a team, which shows some organisational skill',
            ],
            'gaps': [
                'No PRINCE2 or PMP certification',
                'No IT project management experience in a formal sense',
                'No vendor or contract management background',
                'No board-level reporting or steering committee experience',
                'Role is delivery/management focused, not engineering',
            ],
        },
        'brutal': {
            'score': 1,
            'reasoning': (
                'Career mismatch. The candidate is a hands-on engineer; this role '
                'requires no coding and is centred on stakeholder management, vendor '
                'coordination, and formal PM methodology. The skill sets do not overlap.'
            ),
            'strengths': [
                'None that are material to this specific role',
            ],
            'gaps': [
                'Not a project manager — is a software engineer',
                'No PM methodology certification',
                'No delivery or governance framework experience',
            ],
        },
    },
    ('fintechltd', 'Senior Backend Engineer'): {
        'normal': {
            'score': 6,
            'reasoning': (
                'Core backend engineering skills (Python, Django/FastAPI, PostgreSQL) '
                'are a strong match. The gap is domain: no fintech or regulated-environment '
                'experience, and the security/compliance depth expected in payments is '
                'not evidenced. High-throughput API work at TechConsult is adjacent.'
            ),
            'strengths': [
                'Python/Django/FastAPI expertise directly matches stack requirements',
                'PostgreSQL performance experience from high-throughput API work',
                'API design track record across multiple roles',
                '10k req/s API at TechConsult demonstrates scale capability',
            ],
            'gaps': [
                'No fintech, payments, or regulated-environment experience',
                'PCI-DSS or FCA compliance work not evidenced',
                'Security-first engineering not prominent in CV narrative',
            ],
        },
        'brutal': {
            'score': 4,
            'reasoning': (
                'Strong generalist backend engineer but this role is in a critical '
                'payments system under FCA regulation. The absence of any compliance, '
                'security-by-design, or financial-domain experience is a significant '
                'risk factor that a hiring bar in a regulated firm will penalise heavily. '
                'Would need substantial fintech onboarding.'
            ),
            'strengths': [
                'Python backend depth is real',
                'PostgreSQL at scale is relevant',
            ],
            'gaps': [
                'No regulated-environment experience whatsoever',
                'No payments or financial systems background',
                'Security engineering depth not demonstrated',
                'Compliance awareness (PCI-DSS, FCA) absent',
            ],
        },
    },
}


class Command(BaseCommand):
    help = 'Populate development database with demo data.'

    def handle(self, *args, **options):
        self._ensure_demo_user()
        self._ensure_admin_user()
        self._ensure_llm_pricing()
        self._ensure_demo_data()

    # ------------------------------------------------------------------

    def _ensure_demo_user(self):
        if User.objects.filter(email=DEMO_EMAIL).exists():
            print(f'Demo user already exists ({DEMO_EMAIL}), skipping.')
            return
        print('Creating demo user...')
        user = User.objects.create_user(DEMO_USERNAME, DEMO_EMAIL, password=None)
        user.is_demo = True
        user.save()
        Profile.objects.create(
            user=user,
            email_updates=False,
            last_accepted_terms=settings.TERMS_VERSION,
        )
        print(f'Done. Demo login: /demo/')

    def _ensure_admin_user(self):
        if User.objects.filter(username=ADMIN_USERNAME).exists():
            print(f'Admin user already exists ({ADMIN_USERNAME}), skipping.')
            return
        print('Creating admin user...')
        user = User.objects.create_user(ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD)
        user.is_staff = True
        user.is_superuser = True
        user.save()
        Profile.objects.create(
            user=user,
            email_updates=False,
            last_accepted_terms=settings.TERMS_VERSION,
        )
        print(f'Done. Email: {ADMIN_EMAIL}  Password: {ADMIN_PASSWORD}')

    def _ensure_llm_pricing(self):
        _PRICING = [
            ("openai", "gpt-4o",      {"completion_tokens": 10.0, "prompt_tokens": 2.5}),
            ("openai", "gpt-4o-mini", {"completion_tokens": 0.6,  "prompt_tokens": 0.15}),
        ]
        for provider, model, price in _PRICING:
            if not LLMPricing.objects.filter(provider=provider, model=model, superseded_at__isnull=True).exists():
                LLMPricing.objects.create(provider=provider, model=model, price=price)
                print(f'Created LLMPricing for {provider}/{model}.')
            else:
                print(f'LLMPricing for {provider}/{model} already exists, skipping.')

    def _ensure_demo_data(self):
        try:
            user = User.objects.get(email=DEMO_EMAIL)
        except User.DoesNotExist:
            print(f'Demo user ({DEMO_EMAIL}) not found, skipping demo data.')
            return

        cv = self._ensure_cv(user)
        self._ensure_companies_and_jobs(user, cv)

    def _ensure_cv(self, user):
        data_dir = Path(settings.DATA_DIR) / user.username
        cvs_dir  = data_dir / '_cvs'

        cv_name = f"{CV_DATA['name']} - {CV_DATA['title']}"
        existing = CV.objects.filter(user=user, name=cv_name).first()
        if existing:
            print(f'CV already exists ({existing.name}), skipping.')
            return existing

        # Build PDF bytes to compute hash
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            _build_cv_pdf(tmp_path)
            pdf_bytes = tmp_path.read_bytes()
        finally:
            os.unlink(tmp_path)

        cv_hash = hashlib.sha256(pdf_bytes).hexdigest()

        cvs_dir.mkdir(parents=True, exist_ok=True)
        file_path = f'_cvs/{cv_hash}.pdf'
        (data_dir / file_path).write_bytes(pdf_bytes)

        cv = CV.objects.create(
            user=user,
            hash=cv_hash,
            name=cv_name,
            file_path=file_path,
        )
        print(f'Created CV: {cv.name}')
        return cv

    def _ensure_companies_and_jobs(self, user, cv):
        for co_data in COMPANIES:
            company, created = Company.objects.get_or_create(
                user=user,
                slug=co_data['slug'],
                defaults={
                    'name':        co_data['name'],
                    'description': co_data['description'],
                    'archived':    co_data.get('archived', False),
                },
            )
            if created:
                print(f'Created company: {company.name}{"  [archived]" if company.archived else ""}')
            else:
                print(f'Company already exists: {company.name}, skipping jobs.')
                continue

            for job_data in co_data['jobs']:
                job = Job.objects.create(
                    company=company,
                    title=job_data['title'],
                    location=job_data.get('location', ''),
                    employment_type=job_data.get('employment_type', ''),
                    experience_level=job_data.get('experience_level', ''),
                    salary=job_data.get('salary', ''),
                    summary=job_data.get('summary', ''),
                    description=job_data.get('description', ''),
                    responsibilities=job_data.get('responsibilities', []),
                    requirements=job_data.get('requirements', []),
                    nice_to_have=job_data.get('nice_to_have', []),
                    source=job_data.get('source', 'text'),
                    archived=job_data.get('archived', False),
                )
                print(f'  Created job: {job.title}{"  [archived]" if job.archived else ""}')

                score_data = SCORES.get((co_data['slug'], job_data['title']))
                if score_data:
                    for mode in ('normal', 'brutal'):
                        s = score_data[mode]
                        Score.objects.get_or_create(
                            job=job, cv=cv, mode=mode,
                            defaults={
                                'score':     s['score'],
                                'reasoning': s['reasoning'],
                                'strengths': s['strengths'],
                                'gaps':      s['gaps'],
                            },
                        )
                    print(f'    Scored: normal={score_data["normal"]["score"]}/10  brutal={score_data["brutal"]["score"]}/10')
