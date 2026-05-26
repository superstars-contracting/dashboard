"""Structured content for the 19 NYC DOB Ch 33 toolbox talks (EN + ES).

This module is the SINGLE SOURCE OF TRUTH for talk content. The
generator (generate_toolbox_talks.py) reads from here and emits the
matching toolbox_talks_source/<slug>_<lang>.html files, which are
then rendered to PDF by apply_toolbox_talks_seed.py.

Each talk has:
  topic_number    int, unique
  slug            kebab-case filename stem
  category        Site / Fall / Scaffold / Demo / General
  ch33_ref        DOB Ch 33 section citation
  est_minutes     usually 15
  title_en / title_es
  why_en / why_es           2-3 sentences
  rules_en[] / rules_es[]   3-5 bullets (rules with section refs)
  do_en[] / do_es[]         3-5 action bullets
  dont_en[] / dont_es[]     3-5 don't bullets
  questions_en[] / questions_es[]  2-3 discussion questions

Spanish vocabulary: real NYC / Latin-American jobsite Spanish, NOT
classroom Spanish or Spanglish. Industry terms preserved (andamio,
arnés, casco, línea de vida, etc.).
"""

# Talks get added here as we author them. Authoring discipline:
# add ONE talk, regenerate HTMLs, render PDFs, verify single page,
# commit + push. Do NOT batch 19 in memory before any commit
# (context stall would lose work — per handoff).
TALKS = [
    # ============================================================
    # Topic 1 — Pre-Shift Safety Meeting
    # ============================================================
    {
        "topic_number": 1,
        "slug": "01-pre-shift-safety-meeting",
        "category": "Site",
        "ch33_ref": "§3301.12",
        "est_minutes": 15,
        "title_en": "Pre-Shift Safety Meeting — Why We're Here",
        "title_es": "Reunión de Seguridad Antes del Turno — Por Qué Estamos Aquí",
        "why_en": (
            "Every workday on a NYC construction site starts with a pre-shift "
            "safety meeting before any tool comes out. It is when we name today's "
            "hazards, assign jobs, and confirm every worker — new or experienced "
            "— knows what to watch for. Skipping it is how people get hurt."
        ),
        "why_es": (
            "Cada día de trabajo en una obra en NYC empieza con una reunión de "
            "seguridad antes de sacar la primera herramienta. Es cuando nombramos "
            "los peligros del día, asignamos las tareas y confirmamos que cada "
            "trabajador — nuevo o con experiencia — sabe qué cuidar. Saltarla es "
            "cómo la gente sale lastimada."
        ),
        "rules_en": [
            ("Daily pre-shift safety meeting before any work begins.", "§3301.12"),
            ("Foreman or Site Safety Coordinator runs the meeting.", "§3301.12"),
            ("Cover today's hazards, work locations, and assignments.", "§3301.12"),
            ("Every worker signs the attendance log — no exceptions.", "§3301.12"),
            ("A new worker gets the site-specific orientation FIRST.", "§3301.12 / §3321"),
        ],
        "rules_es": [
            ("Reunión diaria de seguridad antes de cualquier trabajo.", "§3301.12"),
            ("El capataz o coordinador de seguridad dirige la reunión.", "§3301.12"),
            ("Hablar de peligros, lugares y asignaciones del día.", "§3301.12"),
            ("Cada trabajador firma la lista de asistencia — sin excepción.", "§3301.12"),
            ("Trabajador nuevo recibe la orientación del sitio PRIMERO.", "§3301.12 / §3321"),
        ],
        "do_en": [
            "Arrive on time — gloves on, hard hat on, no headphones.",
            "Speak up: if you saw a hazard yesterday, say it now.",
            "If you don't understand the plan, ask before walking out to work.",
            "Confirm your assigned location and your work partner.",
            "Sign the attendance log — that is our daily proof.",
        ],
        "do_es": [
            "Llega a tiempo — guantes puestos, casco puesto, sin audífonos.",
            "Habla: si viste un peligro ayer, dilo ahora.",
            "Si no entiendes el plan, pregunta antes de salir a trabajar.",
            "Confirma tu lugar asignado y tu compañero de trabajo.",
            "Firma la lista de asistencia — esa es nuestra prueba diaria.",
        ],
        "dont_en": [
            "Don't start work before the meeting is over.",
            "Don't sign for someone else — that is payroll and safety fraud.",
            "Don't assume yesterday's hazards are today's — the site changes overnight.",
            "Don't stay silent if you have a concern.",
        ],
        "dont_es": [
            "No empieces a trabajar antes de que termine la reunión.",
            "No firmes por otro — eso es fraude de nómina y de seguridad.",
            "No asumas que los peligros de ayer son los de hoy — el sitio cambia.",
            "No te quedes callado si tienes una preocupación.",
        ],
        "questions_en": [
            "What is the most likely hazard at your station today?",
            "If someone gets hurt right now, who do you call first and what do you say?",
            "Is there any equipment or PPE you need today that you don't have?",
        ],
        "questions_es": [
            "¿Cuál es el peligro más probable en tu estación hoy?",
            "Si alguien se lastima ahora, ¿a quién llamas primero y qué le dices?",
            "¿Hay equipo o PPE que necesitas hoy y no tienes?",
        ],
        "description": "Pre-shift safety meeting — purpose, who runs it, what gets covered, and why no one starts work before it ends.",
    },

    # ============================================================
    # Topic 2 — Incident Response
    # ============================================================
    {
        "topic_number": 2,
        "slug": "02-incident-response",
        "category": "Site",
        "ch33_ref": "§3301.6 / §3301.7 / §3301.8",
        "est_minutes": 15,
        "title_en": "Incident Response — What To Do When Something Happens",
        "title_es": "Respuesta a Incidentes — Qué Hacer Cuando Algo Pasa",
        "why_en": (
            "When someone gets hurt — or almost gets hurt — the first ten "
            "minutes decide everything. Confused, late, or missing reports turn "
            "fixable incidents into hospital stays, FDNY complaints, and DOB "
            "violations. This is what every crew member must know cold."
        ),
        "why_es": (
            "Cuando alguien se lastima — o casi se lastima — los primeros diez "
            "minutos lo deciden todo. Reportes confusos, tarde o faltantes "
            "convierten incidentes manejables en hospitalizaciones, quejas a "
            "FDNY y violaciones del DOB. Esto lo tiene que saber cada miembro "
            "del equipo de memoria."
        ),
        "rules_en": [
            ("Call 911 first if injury is serious — bleeding, unconscious, fall.", "§3301.6"),
            ("Notify the Site Safety Coordinator immediately on any incident.", "§3301.6 / §3301.8"),
            ("DOB must be notified of any reportable accident.", "§3301.6"),
            ("Preserve the scene — do not move equipment or debris.", "§3301.7"),
            ("Get witness statements the SAME day, while memory is fresh.", "§3301.7"),
        ],
        "rules_es": [
            ("Llama al 911 primero si la lesión es grave — sangrado, inconsciente, caída.", "§3301.6"),
            ("Notifica al Coordinador de Seguridad inmediatamente.", "§3301.6 / §3301.8"),
            ("Hay que notificar al DOB de todo accidente reportable.", "§3301.6"),
            ("Preserva la escena — no muevas equipo ni escombros.", "§3301.7"),
            ("Toma declaraciones de testigos el MISMO día.", "§3301.7"),
        ],
        "do_en": [
            "Call 911 if anyone is unconscious, bleeding heavily, or fell.",
            "Stop work in the affected area.",
            "Notify Foreman and Site Safety Coordinator by phone — not text.",
            "Write down what you saw before talking to others.",
            "Stay on site until you give your statement.",
        ],
        "do_es": [
            "Llama al 911 si alguien está inconsciente, sangrando mucho, o se cayó.",
            "Para el trabajo en el área afectada.",
            "Avisa al capataz y al Coordinador de Seguridad por teléfono — no texto.",
            "Escribe lo que viste antes de hablar con otros.",
            "Quédate en el sitio hasta dar tu declaración.",
        ],
        "dont_en": [
            "Don't move the injured worker if it could make injury worse.",
            "Don't clean up the scene before the SSC sees it.",
            "Don't discuss fault on site — give facts only.",
            "Don't post photos or details on social media.",
            "Don't leave the site before your statement is taken.",
        ],
        "dont_es": [
            "No muevas al herido si puede empeorar la lesión.",
            "No limpies la escena antes de que el Coordinador la vea.",
            "No discutas de quién tuvo la culpa — solo los hechos.",
            "No publiques fotos ni detalles en redes sociales.",
            "No te vayas antes de dar tu declaración.",
        ],
        "questions_en": [
            "Where is the nearest first-aid kit and AED on this site?",
            "Who is the Site Safety Coordinator today, and what is their phone number?",
            "If you saw a near-miss right now, would you report it? Why or why not?",
        ],
        "questions_es": [
            "¿Dónde está el botiquín de primeros auxilios y el AED más cercanos?",
            "¿Quién es el Coordinador de Seguridad hoy y cuál es su número?",
            "Si vieras un cuasi-accidente ahora, ¿lo reportarías? ¿Por qué sí o no?",
        ],
        "description": "Incident response — first ten minutes, who to call, scene preservation, and what NOT to do (move bodies, clean up, post photos).",
    },

    # ============================================================
    # Topic 3 — SST Cards & Worker Qualifications
    # ============================================================
    {
        "topic_number": 3,
        "slug": "03-sst-cards-qualifications",
        "category": "Site",
        "ch33_ref": "§3321",
        "est_minutes": 15,
        "title_en": "Site Safety Training (SST) Cards & Worker Qualifications",
        "title_es": "Tarjetas SST y Calificaciones del Trabajador",
        "why_en": (
            "NYC law requires every construction worker on a covered site to "
            "carry a valid SST card. No card means no work — period. Foremen and "
            "Supervisors carry the higher-tier SST Supervisor card. A lost, "
            "expired, or wrong-tier card stops work for the whole crew."
        ),
        "why_es": (
            "La ley de NYC requiere que cada trabajador en una obra cubierta "
            "lleve una tarjeta SST válida. Sin tarjeta no hay trabajo — punto. "
            "Capataces y Supervisores llevan la tarjeta SST de Supervisor. Una "
            "tarjeta perdida, vencida, o del nivel equivocado para el trabajo "
            "es una parada de trabajo para toda la cuadrilla."
        ),
        "rules_en": [
            ("Every worker carries a valid SST card on their person.", "§3321"),
            ("Workers: 40-hour SST or active SST Trainee card.", "§3321"),
            ("Foremen / Supervisors: 62-hour SST Supervisor card.", "§3321"),
            ("Refresher: 8 hours every 5 years (workers); 16 hours (supervisors).", "§3321"),
            ("The Site Safety Plan documents which card each role needs.", "§3321"),
        ],
        "rules_es": [
            ("Cada trabajador lleva una tarjeta SST válida con él.", "§3321"),
            ("Trabajadores: SST de 40 horas o tarjeta activa de Aprendiz SST.", "§3321"),
            ("Capataces / Supervisores: tarjeta SST de Supervisor de 62 horas.", "§3321"),
            ("Renovación: 8 horas cada 5 años (trabajadores); 16 horas (supervisores).", "§3321"),
            ("El Plan de Seguridad documenta qué tarjeta necesita cada rol.", "§3321"),
        ],
        "do_en": [
            "Carry your SST card in your wallet — show it on request.",
            "Check the expiration date the day you receive your card.",
            "Tell the Foreman 30 days before expiration to renew.",
            "Foremen: verify the SST tier matches the role before assigning.",
            "Keep a digital photo of the card as a backup.",
        ],
        "do_es": [
            "Carga tu tarjeta SST en la cartera — muéstrala cuando te la pidan.",
            "Revisa la fecha de vencimiento el día que recibes la tarjeta.",
            "Avisa al capataz 30 días antes del vencimiento para renovar.",
            "Capataces: verifica que el nivel SST coincida con el puesto.",
            "Guarda una foto digital de la tarjeta como respaldo.",
        ],
        "dont_en": [
            "Don't lend your card to anyone.",
            "Don't take a role that exceeds your SST tier.",
            "Don't keep working past expiration — that stops the whole crew.",
            "Don't show a photocopy on a DOB inspection.",
        ],
        "dont_es": [
            "No prestes tu tarjeta a nadie.",
            "No aceptes un puesto que pase de tu nivel SST.",
            "No sigas trabajando si está vencida — para a toda la cuadrilla.",
            "No muestres una fotocopia en una inspección del DOB.",
        ],
        "questions_en": [
            "What tier SST card do you carry, and when does it expire?",
            "What's the next SST class our office is sending workers to?",
            "If DOB walked on site right now, would every worker pass an SST check?",
        ],
        "questions_es": [
            "¿Qué nivel de tarjeta SST cargas y cuándo se vence?",
            "¿Cuál es la próxima clase de SST a la que la oficina enviará trabajadores?",
            "Si el DOB llegara ahora, ¿pasaría toda la cuadrilla la verificación de SST?",
        ],
        "description": "SST card tiers, expirations, and what happens when a worker shows up with no card or the wrong one.",
    },
]

