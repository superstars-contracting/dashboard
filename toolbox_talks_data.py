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

    # ============================================================
    # Topic 4 — Adjoining Property Protection
    # ============================================================
    {
        "topic_number": 4,
        "slug": "04-adjoining-property-protection",
        "category": "Site",
        "ch33_ref": "§3309",
        "est_minutes": 15,
        "title_en": "Adjoining Property Protection — Windows, Sills, Neighbors",
        "title_es": "Protección de Propiedad Vecina — Ventanas, Repisas, Vecinos",
        "why_en": (
            "Facade restoration in a row of NYC buildings means our drop, our "
            "scaffold, and our tools are inches from someone else's window, "
            "garden, fire escape, or air conditioner. One brick the wrong way, "
            "one falling tool, and the building owner has a lawsuit and we "
            "have a DOB stop-work."
        ),
        "why_es": (
            "Restaurar fachadas en una fila de edificios de NYC significa que "
            "nuestra caída, nuestro andamio y nuestras herramientas están a "
            "pulgadas de la ventana, jardín, escalera de incendios o aire "
            "acondicionado de otra persona. Un ladrillo mal puesto o una "
            "herramienta que se cae, y el dueño nos demanda y el DOB nos para "
            "el trabajo."
        ),
        "rules_en": [
            ("Inspect adjoining property before work starts — photo evidence.", "§3309.1"),
            ("Owner of the project protects neighboring property from damage.", "§3309.1"),
            ("Notice to adjoining property owners required before work.", "§3309.2"),
            ("Damage to adjoining property reported within 48 hours.", "§3309.4"),
            ("Protective netting / catch platforms over neighboring windows.", "§3309.5 / §3308"),
        ],
        "rules_es": [
            ("Inspecciona la propiedad vecina antes de empezar — con fotos.", "§3309.1"),
            ("El dueño del proyecto protege la propiedad vecina del daño.", "§3309.1"),
            ("Aviso al propietario vecino requerido antes del trabajo.", "§3309.2"),
            ("Daño a propiedad vecina se reporta dentro de 48 horas.", "§3309.4"),
            ("Red protectora o plataforma sobre ventanas vecinas.", "§3309.5 / §3308"),
        ],
        "do_en": [
            "Walk the property line each morning — note any new damage.",
            "Photo every adjoining window and sill BEFORE the first drop.",
            "Tether every tool over 8 ft of ground or scaffold edge.",
            "Stop work immediately if a brick or tool drops outside the line.",
            "Report contact with neighbor to the Foreman the same shift.",
        ],
        "do_es": [
            "Camina la línea de propiedad cada mañana — anota daños nuevos.",
            "Fotografía cada ventana y repisa vecina ANTES de la primera caída.",
            "Amarra cada herramienta sobre 8 pies de tierra o el borde del andamio.",
            "Para el trabajo si un ladrillo o herramienta cae fuera de la línea.",
            "Reporta cualquier contacto con vecinos al capataz el mismo turno.",
        ],
        "dont_en": [
            "Don't lean tools, hoses, or material on a neighbor's wall or AC.",
            "Don't dump debris into a neighbor's airshaft or garden.",
            "Don't argue with a neighbor — refer them to the Foreman.",
            "Don't move past a damaged window without flagging it.",
        ],
        "dont_es": [
            "No apoyes herramientas, mangueras ni material en pared o aire del vecino.",
            "No tires escombros al pozo de luz ni al jardín del vecino.",
            "No discutas con un vecino — refiérelo al capataz.",
            "No pases por una ventana dañada sin reportarla.",
        ],
        "questions_en": [
            "Which neighboring window is closest to your drop today?",
            "If a brick fell on a neighbor's AC right now, what is the first call?",
            "Are the catch platforms / netting still where they were yesterday?",
        ],
        "questions_es": [
            "¿Qué ventana vecina está más cerca de tu caída hoy?",
            "Si un ladrillo cayera ahora en el aire del vecino, ¿cuál es la primera llamada?",
            "¿Las plataformas o redes de protección siguen donde estaban ayer?",
        ],
        "description": "Adjoining property protection during facade work — pre-photos, notice, netting, and what to do when a neighbor's window gets hit.",
    },

    # ============================================================
    # Topic 5 — Sidewalk Shed & Pedestrian Protection
    # ============================================================
    {
        "topic_number": 5,
        "slug": "05-sidewalk-shed-pedestrian-protection",
        "category": "Site",
        "ch33_ref": "§3307",
        "est_minutes": 15,
        "title_en": "Sidewalk Shed & Pedestrian Protection — Daily Check",
        "title_es": "Cobertizo de Acera y Protección al Peatón — Inspección Diaria",
        "why_en": (
            "The sidewalk shed is the one piece of our site every passerby "
            "trusts with their life. A loose panel, a missing light, a "
            "cracked deck — pedestrians don't see the danger, they just walk "
            "under it. We check the shed every morning so nothing falls on "
            "the public."
        ),
        "why_es": (
            "El cobertizo de la acera es la única parte de la obra en la que "
            "cada peatón confía con su vida. Un panel suelto, una luz "
            "faltante, una tabla rajada — los peatones no ven el peligro, "
            "solo pasan debajo. Inspeccionamos el cobertizo cada mañana para "
            "que nada caiga sobre el público."
        ),
        "rules_en": [
            ("Sidewalk shed required when work is >40 ft above grade or per code.", "§3307.6"),
            ("Daily inspection — Foreman or competent person, documented.", "§3307.6.5"),
            ("Lighting on the shed: minimum 2 foot-candles, on dusk to dawn.", "§3307.6.4"),
            ("Decking watertight; no gaps wider than 1 inch.", "§3307.6.2"),
            ("Parapet / netting prevents tools or debris from going over.", "§3307.6.3"),
        ],
        "rules_es": [
            ("Cobertizo requerido cuando el trabajo está >40 pies sobre la acera.", "§3307.6"),
            ("Inspección diaria — capataz o persona competente, documentada.", "§3307.6.5"),
            ("Iluminación: mínimo 2 foot-candles, prendida del atardecer al amanecer.", "§3307.6.4"),
            ("Cubierta impermeable; sin grietas más anchas de 1 pulgada.", "§3307.6.2"),
            ("Parapeto o red impide que herramientas o escombros se caigan.", "§3307.6.3"),
        ],
        "do_en": [
            "Walk the shed at 7 AM — look up, look down, look at the lights.",
            "Sweep debris off the deck before the shift starts.",
            "Replace any burnt-out shed light THE SAME DAY.",
            "Re-tie loose plywood or netting before going up.",
            "Document the inspection on the shed log (every day).",
        ],
        "do_es": [
            "Camina el cobertizo a las 7 AM — mira arriba, abajo y las luces.",
            "Barre los escombros del techo antes de empezar el turno.",
            "Reemplaza cualquier luz quemada del cobertizo EL MISMO DÍA.",
            "Reata el plywood o la red suelta antes de subir.",
            "Documenta la inspección en la bitácora del cobertizo (todos los días).",
        ],
        "dont_en": [
            "Don't store material on the shed deck — it loads it past spec.",
            "Don't block the pedestrian walkway with material or trash.",
            "Don't leave tools on top of the shed at end of shift.",
            "Don't ignore graffiti on the shed — note + report it.",
        ],
        "dont_es": [
            "No guardes material sobre el cobertizo — lo sobrecarga.",
            "No bloquees el paso peatonal con material ni basura.",
            "No dejes herramientas arriba del cobertizo al final del turno.",
            "No ignores el grafiti en el cobertizo — anótalo y repórtalo.",
        ],
        "questions_en": [
            "Are all shed lights working right now? When did we last check?",
            "What's on the shed deck that shouldn't be?",
            "If a pedestrian got hit by something falling, where would you look first?",
        ],
        "questions_es": [
            "¿Funcionan todas las luces del cobertizo ahora? ¿Cuándo lo revisamos?",
            "¿Qué hay arriba del cobertizo que no debería estar?",
            "Si algo cayera sobre un peatón, ¿dónde mirarías primero?",
        ],
        "description": "Sidewalk shed daily check — lighting, decking, debris on top, and the public's safety underneath.",
    },

    # ============================================================
    # Topic 6 — Housekeeping & Combustible Debris
    # ============================================================
    {
        "topic_number": 6,
        "slug": "06-housekeeping-combustible-debris",
        "category": "Site",
        "ch33_ref": "§3303.4 / §3303.5",
        "est_minutes": 15,
        "title_en": "Housekeeping & Combustible Debris Control",
        "title_es": "Limpieza y Control de Escombros Combustibles",
        "why_en": (
            "Most jobsite fires start in trash. Wood, cardboard, oily rags, "
            "and resin tubs left in a pile near a torch or grinder are how a "
            "clean facade job ends up on the FDNY news at six. Housekeeping "
            "is not just tidy — it's the cheapest fire control we have."
        ),
        "why_es": (
            "La mayoría de los incendios en obras empiezan en la basura. "
            "Madera, cartón, trapos con aceite, y botes de resina dejados "
            "en pila cerca de un soplete o esmeril son cómo un trabajo de "
            "fachada limpia termina en las noticias de FDNY a las seis. La "
            "limpieza no es solo orden — es el control de fuego más barato "
            "que tenemos."
        ),
        "rules_en": [
            ("Combustible waste removed from work area at end of each shift.", "§3303.4"),
            ("Metal cans with lids for oily rags — emptied daily.", "§3303.5"),
            ("Smoking only in designated areas — never near combustibles.", "§3303.4"),
            ("Walkways and exits kept clear of debris at all times.", "§3303.4"),
            ("Flammable liquids stored in approved containers, away from heat.", "§3303.5"),
        ],
        "rules_es": [
            ("Basura combustible se saca del área al final de cada turno.", "§3303.4"),
            ("Latas de metal con tapa para trapos con aceite — vaciadas a diario.", "§3303.5"),
            ("Fumar solo en áreas designadas — nunca cerca de combustibles.", "§3303.4"),
            ("Pasillos y salidas libres de escombros todo el tiempo.", "§3303.4"),
            ("Líquidos inflamables en envases aprobados, lejos del calor.", "§3303.5"),
        ],
        "do_en": [
            "Bag and bin debris hourly — don't let piles build up.",
            "Use the metal oily-rag can — close the lid every time.",
            "Sweep your station before lunch and before you leave.",
            "Walk a 10-ft circle around any hot work to clear flammables.",
            "Empty trash to the dumpster before end of shift, not Monday.",
        ],
        "do_es": [
            "Embolsa y tira escombros cada hora — no dejes que se acumulen.",
            "Usa la lata de metal para trapos con aceite — cierra la tapa siempre.",
            "Barre tu puesto antes del almuerzo y antes de irte.",
            "Camina 10 pies alrededor de cualquier soplete para sacar inflamables.",
            "Vacía la basura al contenedor antes del final del turno, no el lunes.",
        ],
        "dont_en": [
            "Don't pile cardboard or wood near a torch, grinder, or saw.",
            "Don't smoke or vape outside the designated smoking zone.",
            "Don't dump solvents into trash bags — they ignite.",
            "Don't let oily rags sit loose — they spontaneously combust.",
        ],
        "dont_es": [
            "No apiles cartón ni madera cerca de soplete, esmeril o sierra.",
            "No fumes ni vapees fuera del área designada para fumadores.",
            "No tires solventes en bolsas de basura — se prenden.",
            "No dejes trapos con aceite sueltos — se combustionan solos.",
        ],
        "questions_en": [
            "Where is the oily-rag can on this site, and when was it last emptied?",
            "Show me one combustible pile within 10 feet of hot work right now.",
            "What's the fastest path from your station to the nearest extinguisher?",
        ],
        "questions_es": [
            "¿Dónde está la lata de trapos con aceite, y cuándo se vació?",
            "Muéstrame una pila combustible a menos de 10 pies de un soplete ahora.",
            "¿Cuál es el camino más rápido de tu puesto al extintor más cercano?",
        ],
        "description": "Housekeeping and combustible debris — why most jobsite fires start in trash and how to keep work zones clear.",
    },

    # ============================================================
    # Topic 7 — Fire Safety During Construction
    # ============================================================
    {
        "topic_number": 7,
        "slug": "07-fire-safety-hot-work",
        "category": "Site",
        "ch33_ref": "§3303.7 / §3303.8",
        "est_minutes": 15,
        "title_en": "Fire Safety During Construction — Hot Work, Extinguishers, Standpipe",
        "title_es": "Seguridad Contra Incendios — Trabajo en Caliente, Extintores, Tubería Vertical",
        "why_en": (
            "Hot work — torch cutting, welding, grinding sparks — is the "
            "single highest-risk activity on a facade job. A spark drops "
            "three floors into a pile of cardboard, smolders for two hours, "
            "ignites after we leave. Most construction fires are not "
            "discovered until it's too late."
        ),
        "why_es": (
            "El trabajo en caliente — corte con soplete, soldadura, chispas "
            "de esmeril — es la actividad de más alto riesgo en una fachada. "
            "Una chispa cae tres pisos a una pila de cartón, arde dos horas, "
            "se prende después de irnos. La mayoría de los incendios no se "
            "descubren hasta que ya es tarde."
        ),
        "rules_en": [
            ("Hot work permit required before any cutting, welding, brazing.", "§3303.7.2"),
            ("Fire watch posted during hot work and 30 min after.", "§3303.7.4"),
            ("Portable extinguisher within 25 ft of every hot-work station.", "§3303.7.5"),
            ("Working standpipe required when building is >75 ft.", "§3303.8"),
            ("FDNY S-56 Certificate of Fitness holder must be on site.", "§3303.7.1"),
        ],
        "rules_es": [
            ("Permiso de trabajo en caliente requerido antes de cortar o soldar.", "§3303.7.2"),
            ("Vigilante de incendio durante el trabajo y 30 min después.", "§3303.7.4"),
            ("Extintor portátil a menos de 25 pies de cada estación caliente.", "§3303.7.5"),
            ("Tubería vertical funcional requerida cuando el edificio es >75 pies.", "§3303.8"),
            ("Titular del Certificado FDNY S-56 debe estar en sitio.", "§3303.7.1"),
        ],
        "do_en": [
            "Pull a hot work permit and post it at the work location.",
            "Clear a 35-foot radius of combustibles before starting.",
            "Station a fire watch with a charged extinguisher.",
            "Keep watching for 30 minutes after the torch is off.",
            "Confirm the standpipe is charged before going above 75 ft.",
        ],
        "do_es": [
            "Saca el permiso de trabajo en caliente y póngalo en el sitio del trabajo.",
            "Despeja 35 pies a la redonda de combustibles antes de empezar.",
            "Pon un vigilante de incendio con un extintor cargado.",
            "Sigue vigilando 30 minutos después de apagar el soplete.",
            "Confirma que la tubería vertical esté cargada antes de subir arriba de 75 pies.",
        ],
        "dont_en": [
            "Don't cut, weld, or grind without a current hot work permit.",
            "Don't leave hot work unattended — even for a minute.",
            "Don't use a damaged or undischarged extinguisher.",
            "Don't block the standpipe inlet or extinguisher access.",
        ],
        "dont_es": [
            "No cortes, sueldes ni esmeriles sin un permiso vigente.",
            "No dejes trabajo en caliente sin vigilancia — ni un minuto.",
            "No uses un extintor dañado o descargado.",
            "No bloquees la entrada de la tubería vertical ni el acceso al extintor.",
        ],
        "questions_en": [
            "Who holds the S-56 Certificate on this site, and where are they right now?",
            "Where is the closest extinguisher to your work station? Is it charged?",
            "What happens to a spark that falls behind a window opening?",
        ],
        "questions_es": [
            "¿Quién tiene el Certificado S-56 en este sitio, y dónde está ahora?",
            "¿Dónde está el extintor más cercano a tu puesto? ¿Está cargado?",
            "¿Qué pasa con una chispa que cae detrás de una ventana abierta?",
        ],
        "description": "Hot work fire safety — permits, fire watch, extinguishers, the standpipe rule, and FDNY S-56 holders.",
    },
]

