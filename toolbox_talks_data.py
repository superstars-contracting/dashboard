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

    # ============================================================
    # Topic 8 — Unenclosed Perimeter Protection
    # ============================================================
    {
        "topic_number": 8,
        "slug": "08-unenclosed-perimeter-protection",
        "category": "Fall",
        "ch33_ref": "§3308",
        "est_minutes": 15,
        "title_en": "Unenclosed Perimeter Protection — Guards & Netting",
        "title_es": "Protección del Perímetro Abierto — Barandales y Redes",
        "why_en": (
            "Every open edge above 6 feet is a fall waiting to happen — for "
            "us and for anything we drop. Guardrails and perimeter netting "
            "are not decoration. A loose rail or a sagging net is the line "
            "between a normal Tuesday and a coroner's report. Check the "
            "perimeter every shift."
        ),
        "why_es": (
            "Cada borde abierto arriba de 6 pies es una caída esperando "
            "pasar — para nosotros y para todo lo que se nos caiga. Los "
            "barandales y las redes del perímetro no son decoración. Una "
            "baranda floja o una red colgada es la línea entre un martes "
            "normal y un reporte de muerte. Revisa el perímetro cada turno."
        ),
        "rules_en": [
            ("Guardrails at every open edge >6 ft above lower level.", "§3308.4"),
            ("Top rail 42 inches ±3, mid-rail at 21 inches, 4-inch toe board.", "§3308.4.1"),
            ("Perimeter netting on every floor above grade during construction.", "§3308.5"),
            ("Netting inspected weekly + after any drop event.", "§3308.5.3"),
            ("Holes / openings >2 inches covered, marked, and secured.", "§3308.6"),
        ],
        "rules_es": [
            ("Barandales en cada borde abierto >6 pies de altura.", "§3308.4"),
            ("Riel superior 42 pulg ±3, riel medio 21 pulg, tabla 4 pulg.", "§3308.4.1"),
            ("Red perimetral en cada piso arriba del suelo durante construcción.", "§3308.5"),
            ("La red se inspecciona semanalmente y después de cualquier caída.", "§3308.5.3"),
            ("Huecos >2 pulgadas cubiertos, marcados y asegurados.", "§3308.6"),
        ],
        "do_en": [
            "Walk the perimeter at start of shift — push every rail, check height.",
            "Replace damaged netting before continuing work on that floor.",
            "Tie off if you must remove a guardrail temporarily.",
            "Cover floor openings the second you see them — even just plywood + screws.",
            "Report a loose or missing rail to the Foreman immediately.",
        ],
        "do_es": [
            "Camina el perímetro al inicio del turno — empuja cada baranda, mide altura.",
            "Reemplaza red dañada antes de seguir trabajando en ese piso.",
            "Amárrate si tienes que quitar una baranda temporalmente.",
            "Cubre huecos del piso al verlos — aunque sea plywood y tornillos.",
            "Reporta baranda floja o faltante al capataz de inmediato.",
        ],
        "dont_en": [
            "Don't remove a guardrail unless you're tied off and have approval.",
            "Don't use a guardrail to hang material, tools, or hoses.",
            "Don't step on a covered floor opening — walk around.",
            "Don't trust netting after a heavy drop — inspect before using it.",
        ],
        "dont_es": [
            "No quites una baranda sin estar amarrado y con permiso.",
            "No uses la baranda para colgar material, herramientas, ni mangueras.",
            "No pises un hueco tapado — camina alrededor.",
            "No confíes en la red después de una caída fuerte — inspecciónala.",
        ],
        "questions_en": [
            "Push the nearest guardrail right now — does it move more than an inch?",
            "When was the perimeter netting last inspected on your floor?",
            "Where's the closest uncovered floor opening you've seen this week?",
        ],
        "questions_es": [
            "Empuja la baranda más cercana ahora — ¿se mueve más de una pulgada?",
            "¿Cuándo se inspeccionó la red de tu piso por última vez?",
            "¿Dónde está el hueco sin cubrir más cercano que viste esta semana?",
        ],
        "description": "Perimeter protection — guardrails, perimeter netting, floor-opening covers, and what to do before removing any of them.",
    },

    # ============================================================
    # Topic 9 — Personal Fall Arrest Systems
    # ============================================================
    {
        "topic_number": 9,
        "slug": "09-personal-fall-arrest-systems",
        "category": "Fall",
        "ch33_ref": "§3314 + OSHA 1926 Subpart M",
        "est_minutes": 15,
        "title_en": "Personal Fall Arrest Systems — Harness, Lanyard, Rope Grab",
        "title_es": "Sistemas Personales contra Caídas — Arnés, Cabo, Rope Grab",
        "why_en": (
            "On a suspended scaffold our harness is the difference between a "
            "scare and a funeral. A harness worn loose, an unrated anchor, a "
            "rope grab installed upside down — all kill the system silently. "
            "Inspect every piece every time. The fall doesn't care that "
            "you're in a hurry."
        ),
        "why_es": (
            "En un andamio colgante el arnés es la diferencia entre un susto "
            "y un funeral. Un arnés flojo, un anclaje sin calificar, un rope "
            "grab al revés — todos matan el sistema en silencio. Inspecciona "
            "cada pieza cada vez. La caída no le importa que tengas prisa."
        ),
        "rules_en": [
            ("100% tie-off above 6 ft — every worker, every time.", "§3314.4.10"),
            ("Independent vertical lifeline + rope grab for every scaffold occupant.", "§3314.4.10"),
            ("Anchor rated for 5,000 lb per worker, or 2× max arrest force.", "OSHA 1926.502(d)(15)"),
            ("Harness inspected before each use — webbing, D-ring, buckles.", "§3314.4.10 / OSHA"),
            ("Shock-absorbing lanyard ≤6 ft; rope grab oriented per manufacturer.", "OSHA 1926.502(d)"),
        ],
        "rules_es": [
            ("Amarre 100% arriba de 6 pies — cada trabajador, cada vez.", "§3314.4.10"),
            ("Línea de vida vertical + rope grab independiente para cada persona.", "§3314.4.10"),
            ("Anclaje calificado para 5,000 lb por trabajador, o 2× la fuerza máxima.", "OSHA 1926.502(d)(15)"),
            ("Inspeccionar arnés antes de cada uso — correas, D-ring, hebillas.", "§3314.4.10 / OSHA"),
            ("Cabo con absorbedor ≤6 pies; rope grab orientado según el fabricante.", "OSHA 1926.502(d)"),
        ],
        "do_en": [
            "Snug the harness — two fingers under the chest strap, no more.",
            "Inspect webbing inch by inch for cuts, burns, fuzziness.",
            "Connect to the lifeline BEFORE stepping onto the scaffold.",
            "Check the rope grab arrow points UP toward the anchor.",
            "Retire any harness involved in an arrested fall — never reuse.",
        ],
        "do_es": [
            "Aprieta el arnés — dos dedos bajo la correa del pecho, no más.",
            "Inspecciona la correa pulgada por pulgada — cortes, quemaduras, pelusa.",
            "Conéctate a la línea de vida ANTES de pisar el andamio.",
            "Revisa que la flecha del rope grab apunte HACIA ARRIBA al anclaje.",
            "Retira cualquier arnés que paró una caída — nunca lo reuses.",
        ],
        "dont_en": [
            "Don't share lanyards or rope grabs — each worker has their own.",
            "Don't tie off to a railing, pipe, or wire — only rated anchors.",
            "Don't use a body belt as fall protection — it's banned.",
            "Don't extend a lanyard with a knot or a second connector.",
        ],
        "dont_es": [
            "No compartas cabos ni rope grabs — cada trabajador tiene el suyo.",
            "No te amarres a baranda, tubo, ni alambre — solo a anclajes calificados.",
            "No uses cinturón de cuerpo como protección contra caídas — está prohibido.",
            "No extiendas un cabo con nudo ni con un segundo conector.",
        ],
        "questions_en": [
            "Show me your harness — does the chest strap sit at sternum level?",
            "Where is your anchor today and how do you know it's rated?",
            "If you fell into the harness right now, what does the rescue plan say?",
        ],
        "questions_es": [
            "Muéstrame tu arnés — ¿la correa del pecho está al nivel del esternón?",
            "¿Dónde está tu anclaje hoy y cómo sabes que está calificado?",
            "Si cayeras en el arnés ahora, ¿qué dice el plan de rescate?",
        ],
        "description": "Personal fall arrest — fit the harness, inspect the webbing, connect to a rated anchor, retire post-arrest.",
    },

    # ============================================================
    # Topic 10 — Suspended Scaffold Daily Inspection
    # ============================================================
    {
        "topic_number": 10,
        "slug": "10-suspended-scaffold-daily-inspection",
        "category": "Scaffold",
        "ch33_ref": "§3314",
        "est_minutes": 15,
        "title_en": "Suspended Scaffold — Daily Inspection (Companion to the Checklist)",
        "title_es": "Andamio Colgante — Inspección Diaria (Complemento al Checklist)",
        "why_en": (
            "Every shift our scaffold rises and falls on equipment that "
            "wasn't inspected by us when we left yesterday. The competent "
            "person walks the drop, the motors, the wire rope, the harness "
            "anchors, and the cage — every morning. The daily checklist is "
            "the receipt. No checklist, no work."
        ),
        "why_es": (
            "Cada turno nuestro andamio sube y baja en equipo que no "
            "inspeccionamos cuando nos fuimos ayer. La persona competente "
            "camina la caída, los motores, el cable, los anclajes del arnés "
            "y la jaula — cada mañana. El checklist diario es el recibo. "
            "Sin checklist, no hay trabajo."
        ),
        "rules_en": [
            ("Suspended scaffold inspected daily by a competent person before use.", "§3314.4.7"),
            ("Pre-shift inspection of wire rope, motors, stirrups, tiebacks, lifelines.", "§3314.4.7"),
            ("Drop platform load tested to 4× working load at rig-up.", "§3314.4.5"),
            ("Document daily inspection — signature + date on the log.", "§3314.4.7"),
            ("Out-of-service scaffolds tagged and the drop secured.", "§3314.4.8"),
        ],
        "rules_es": [
            ("Andamio inspeccionado diariamente por persona competente antes de usar.", "§3314.4.7"),
            ("Inspección antes del turno — cable, motores, estribos, tiebacks, líneas.", "§3314.4.7"),
            ("Plataforma probada a 4× la carga de trabajo al armar.", "§3314.4.5"),
            ("Documenta la inspección diaria — firma + fecha en el registro.", "§3314.4.7"),
            ("Andamio fuera de servicio se etiqueta y se asegura.", "§3314.4.8"),
        ],
        "do_en": [
            "Inspect from the ground up — outrigger / tieback / wire / motor / stirrup / platform.",
            "Pull-test wire rope hand-over-hand for kinks, broken wires, birdcaging.",
            "Cycle motors up + down empty before crew gets on.",
            "Verify lifelines are independent of the suspension lines.",
            "Sign the daily inspection log BEFORE the first worker boards.",
        ],
        "do_es": [
            "Inspecciona de abajo hacia arriba — outrigger / tieback / cable / motor / estribo / plataforma.",
            "Prueba el cable mano-sobre-mano — torceduras, hilos rotos, birdcaging.",
            "Sube y baja los motores vacíos antes de que se suba la cuadrilla.",
            "Verifica que las líneas de vida sean independientes de las de suspensión.",
            "Firma el registro de inspección diaria ANTES del primer trabajador.",
        ],
        "dont_en": [
            "Don't board a scaffold without seeing today's signed inspection.",
            "Don't skip the cycle test because the scaffold looked fine yesterday.",
            "Don't operate a scaffold with a damaged or kinked suspension rope.",
            "Don't put more than the rated load on the platform — ever.",
        ],
        "dont_es": [
            "No subas a un andamio sin ver la inspección firmada de hoy.",
            "No saltes la prueba de motores porque ayer estaba bien.",
            "No operes un andamio con cable de suspensión dañado o torcido.",
            "No subas más de la carga calificada en la plataforma — nunca.",
        ],
        "questions_en": [
            "Who is the competent person on this scaffold today?",
            "What's one defect on a suspended scaffold that means STOP, not fix later?",
            "Where is today's inspection log right now?",
        ],
        "questions_es": [
            "¿Quién es la persona competente en este andamio hoy?",
            "¿Cuál es un defecto que significa PARAR, no arreglar después?",
            "¿Dónde está el registro de inspección de hoy ahora mismo?",
        ],
        "description": "Suspended scaffold daily inspection — what the competent person checks each morning, in order, and signs.",
    },

    # ============================================================
    # Topic 11 — Tiebacks, Lifelines, Anchorage
    # ============================================================
    {
        "topic_number": 11,
        "slug": "11-suspended-scaffold-tiebacks-lifelines",
        "category": "Scaffold",
        "ch33_ref": "§3314",
        "est_minutes": 15,
        "title_en": "Suspended Scaffold — Tiebacks, Lifelines, Anchorage",
        "title_es": "Andamio Colgante — Tiebacks, Líneas de Vida, Anclajes",
        "why_en": (
            "Counterweights hold the scaffold up. Tiebacks keep it from "
            "tipping when the wind hits or a worker moves. Lifelines catch "
            "us if the scaffold itself fails. These are three separate "
            "systems — not interchangeable, not optional, not for "
            "improvisation. Every anchor we use was designed for THIS load."
        ),
        "why_es": (
            "Los contrapesos sostienen el andamio. Los tiebacks evitan que "
            "se vuelque cuando pega el viento o un trabajador se mueve. Las "
            "líneas de vida nos atrapan si el andamio mismo falla. Son tres "
            "sistemas separados — no intercambiables, no opcionales, no "
            "para improvisar. Cada anclaje que usamos fue diseñado para "
            "ESTA carga."
        ),
        "rules_en": [
            ("Tieback installed at every suspension point before lifting workers.", "§3314.4.6"),
            ("Tieback angle 0–45° from horizontal, opposite of overturning.", "§3314.4.6.2"),
            ("Lifelines independent of suspension lines, anchored separately.", "§3314.4.10"),
            ("Anchorage rated 5,000 lb per worker (or 2× max arrest force).", "§3314.4.10 / OSHA"),
            ("Building anchors PE-stamped on the C-hook / parapet clamp plan.", "§3314.4.6"),
        ],
        "rules_es": [
            ("Tieback instalado en cada punto de suspensión antes de subir trabajadores.", "§3314.4.6"),
            ("Ángulo del tieback 0–45° de horizontal, opuesto al volteo.", "§3314.4.6.2"),
            ("Líneas de vida independientes de suspensión, ancladas aparte.", "§3314.4.10"),
            ("Anclaje calificado a 5,000 lb por trabajador (o 2× la fuerza máx).", "§3314.4.10 / OSHA"),
            ("Anclajes del edificio sellados por PE en el plan de C-hook / parapet.", "§3314.4.6"),
        ],
        "do_en": [
            "Confirm tieback is in place AND tight before stepping on the platform.",
            "Match every lifeline to its own independent anchor — not the rig's.",
            "Visually verify the C-hook plan against what's installed today.",
            "Re-tension a tieback that has gone slack overnight or after wind.",
            "Tag any anchor with deformation or rust loss — pull it from service.",
        ],
        "do_es": [
            "Confirma que el tieback esté puesto Y apretado antes de subir.",
            "Conecta cada línea de vida a su propio anclaje independiente.",
            "Verifica visualmente el plan de C-hook contra lo instalado hoy.",
            "Re-tensa un tieback que se aflojó de noche o con viento.",
            "Etiqueta cualquier anclaje con deformación u oxidación — fuera de uso.",
        ],
        "dont_en": [
            "Don't share a single anchor between two lifelines.",
            "Don't tie back to a pipe, rebar, or weld — only PE-approved anchors.",
            "Don't install a tieback at a downward angle — it must pull horizontally / up.",
            "Don't connect the rope grab to the suspension line.",
        ],
        "dont_es": [
            "No compartas un anclaje entre dos líneas de vida.",
            "No amarres a tubo, varilla, ni soldadura — solo a anclajes aprobados por PE.",
            "No instales un tieback en ángulo hacia abajo — debe jalar horizontal / arriba.",
            "No conectes el rope grab a la línea de suspensión.",
        ],
        "questions_en": [
            "Walk me through your three independent connections right now.",
            "What is the C-hook plan reference on your drop today?",
            "If a tieback came loose mid-shift, what's the immediate action?",
        ],
        "questions_es": [
            "Repasa tus tres conexiones independientes ahora.",
            "¿Cuál es la referencia del plan de C-hook en tu caída de hoy?",
            "Si un tieback se aflojara durante el turno, ¿qué haces de inmediato?",
        ],
        "description": "Three independent systems on a swing-stage drop: counterweights, tiebacks, and lifelines — and the anchor that holds each.",
    },

    # ============================================================
    # Topic 12 — Counterweights, Outriggers, Mudsills
    # ============================================================
    {
        "topic_number": 12,
        "slug": "12-counterweights-outriggers-mudsills",
        "category": "Scaffold",
        "ch33_ref": "§3314",
        "est_minutes": 15,
        "title_en": "Suspended Scaffold — Counterweights, Outriggers, Mudsills",
        "title_es": "Andamio Colgante — Contrapesos, Outriggers, Tablones Base",
        "why_en": (
            "On a parapet-clamp or outrigger drop, the counterweights are "
            "the only thing keeping the rig from rotating off the roof. "
            "Missing one weight, an outrigger on a soft spot, a mudsill on "
            "uneven asphalt — the math fails and the rig goes over the "
            "edge. Verify the math before workers go below."
        ),
        "why_es": (
            "En una caída con parapet-clamp u outrigger, los contrapesos "
            "son lo único que evita que el equipo se voltee del techo. "
            "Falta un peso, un outrigger en un punto blando, un tablón "
            "base sobre asfalto irregular — la matemática falla y el "
            "equipo se va por el borde. Verifica la matemática antes de "
            "que los trabajadores bajen."
        ),
        "rules_en": [
            ("Counterweight = 4× the suspended load (working load × 4 safety factor).", "§3314.4.5"),
            ("Counterweights of equal-weight pieces, not flowable material.", "§3314.4.5.2"),
            ("Outriggers bear on a mudsill that distributes the load to the deck.", "§3314.4.5.3"),
            ("Outrigger anchored / secured against displacement.", "§3314.4.5.3"),
            ("Counterweights labeled with their weight; no missing pieces.", "§3314.4.5.2"),
        ],
        "rules_es": [
            ("Contrapeso = 4× la carga colgada (carga × factor de seguridad 4).", "§3314.4.5"),
            ("Contrapesos de piezas de peso igual, no material que fluye.", "§3314.4.5.2"),
            ("Outriggers se apoyan en un tablón base que distribuye la carga.", "§3314.4.5.3"),
            ("Outrigger anclado o asegurado contra desplazamiento.", "§3314.4.5.3"),
            ("Contrapesos etiquetados con su peso; no falta ninguna pieza.", "§3314.4.5.2"),
        ],
        "do_en": [
            "Re-count counterweights every morning — match the rigging plan.",
            "Check the mudsill is full-contact on the roof deck, no rocking.",
            "Verify each outrigger has its anchor pin or strap engaged.",
            "Measure outrigger fulcrum-to-counterweight distance against the plan.",
            "Mark and store odd-shaped counterweights together — no mixing.",
        ],
        "do_es": [
            "Cuenta contrapesos cada mañana — confirma el plan de rigging.",
            "Verifica que el tablón base toque completo el techo, sin moverse.",
            "Confirma que cada outrigger tenga su pasador o correa puestos.",
            "Mide la distancia outrigger-fulcro-contrapeso contra el plan.",
            "Marca y guarda contrapesos de forma rara juntos — sin mezclar.",
        ],
        "dont_en": [
            "Don't use sand, water drums, or rebar bundles as counterweight.",
            "Don't move counterweights mid-shift without re-checking the math.",
            "Don't put an outrigger on a soft membrane without a load-spreading plate.",
            "Don't let counterweights overhang the roof edge.",
        ],
        "dont_es": [
            "No uses arena, tanques de agua, ni varilla atada como contrapeso.",
            "No muevas contrapesos durante el turno sin recalcular.",
            "No pongas un outrigger sobre membrana suave sin placa.",
            "No dejes contrapesos sobresalir del borde del techo.",
        ],
        "questions_en": [
            "How many counterweights does today's drop require? Show me the math.",
            "Is the mudsill bridging a roof seam or expansion joint?",
            "What happens if one counterweight falls off mid-shift?",
        ],
        "questions_es": [
            "¿Cuántos contrapesos necesita la caída de hoy? Muéstrame la matemática.",
            "¿El tablón base cruza una junta del techo o de expansión?",
            "¿Qué pasa si un contrapeso se cae durante el turno?",
        ],
        "description": "Outrigger / parapet-clamp rig math — 4× counterweight, mudsill, and what happens if a piece walks off.",
    },

    # ============================================================
    # Topic 13 — Wire Rope Termination
    # ============================================================
    {
        "topic_number": 13,
        "slug": "13-wire-rope-termination",
        "category": "Scaffold",
        "ch33_ref": "§3314",
        "est_minutes": 15,
        "title_en": "Wire Rope Termination — Fistgrips, Shackles, Thimbles",
        "title_es": "Terminación de Cable — Fistgrips, Grilletes, Guardacabos",
        "why_en": (
            "Every fall arrest and every scaffold suspension ends in a "
            "wire-rope termination. Get the fistgrip orientation wrong, "
            "skip the thimble, undersize the shackle — and a perfectly "
            "good rope slips at the worst moment. The terminations are "
            "what the engineers calculated; we don't get creative with them."
        ),
        "why_es": (
            "Toda detención de caída y toda suspensión de andamio termina "
            "en una terminación de cable. Pon el fistgrip al revés, salta "
            "el guardacabos, usa grillete chico — y un cable perfectamente "
            "bueno se zafa en el peor momento. Las terminaciones son lo "
            "que el ingeniero calculó; no las improvisamos."
        ),
        "rules_en": [
            ("Minimum 3 fistgrips on 3/8-in or smaller wire rope; more for larger.", "§3314.4.5.6"),
            ("Saddle of the fistgrip on the LIVE side, U-bolt on the dead end.", "§3314.4.5.6"),
            ("Thimble required in every eye-loop — no kinking the rope around shackles.", "§3314.4.5.6"),
            ("Shackle pin oriented so vibration doesn't unscrew it; mouse it.", "§3314.4.5.6"),
            ("Re-torque fistgrip nuts after the first load (rope settles).", "§3314.4.5.6"),
        ],
        "rules_es": [
            ("Mínimo 3 fistgrips en cable 3/8 pulg o menor; más en cables grandes.", "§3314.4.5.6"),
            ("La silla del fistgrip en el lado VIVO, el U-bolt en el extremo muerto.", "§3314.4.5.6"),
            ("Guardacabos en cada lazo — no torcer el cable directo en el grillete.", "§3314.4.5.6"),
            ("Pasador del grillete orientado para que la vibración no lo afloje; amárralo.", "§3314.4.5.6"),
            ("Vuelve a apretar las tuercas del fistgrip después de la primera carga.", "§3314.4.5.6"),
        ],
        "do_en": [
            "Inspect every termination at rig-up and again after first load.",
            "Confirm fistgrip saddle is on the load side — 'never saddle a dead horse.'",
            "Use a thimble inside every eye — no exceptions.",
            "Match shackle size to rope diameter per the rigging plan.",
            "Mouse the shackle pin with seizing wire to prevent backout.",
        ],
        "do_es": [
            "Inspecciona cada terminación al armar y otra vez después de la primera carga.",
            "Confirma que la silla del fistgrip esté del lado vivo.",
            "Usa guardacabos dentro de cada lazo — sin excepción.",
            "El tamaño del grillete coincide con el diámetro del cable según el plan.",
            "Amarra el pasador del grillete con alambre para que no se zafe.",
        ],
        "dont_en": [
            "Don't put fistgrip saddles on the dead end — that crushes the load side.",
            "Don't reuse an eye that's been kinked or pulled past spec.",
            "Don't substitute a smaller shackle to make it 'fit' the hole.",
            "Don't paint or grease over a termination — it hides cracks.",
        ],
        "dont_es": [
            "No pongas la silla del fistgrip en el extremo muerto — aplasta el lado vivo.",
            "No reutilices un lazo torcido o que pasó del límite.",
            "No sustituyas un grillete chico para que entre en el agujero.",
            "No pintes ni engrases una terminación — esconde grietas.",
        ],
        "questions_en": [
            "Show me a fistgrip on the scaffold — which side is the saddle on?",
            "How many fistgrips does the rigging plan call for at this site?",
            "What's the inspection criterion to retire a wire rope?",
        ],
        "questions_es": [
            "Muéstrame un fistgrip en el andamio — ¿de qué lado está la silla?",
            "¿Cuántos fistgrips pide el plan de rigging en este sitio?",
            "¿Cuál es el criterio para retirar un cable de servicio?",
        ],
        "description": "Wire rope terminations — fistgrip orientation, thimbles, shackle sizing, mousing, and re-torque after first load.",
    },

    # ============================================================
    # Topic 14 — Demolition Safety
    # ============================================================
    {
        "topic_number": 14,
        "slug": "14-demolition-safety",
        "category": "Demo",
        "ch33_ref": "§3306",
        "est_minutes": 15,
        "title_en": "Demolition Safety — Sequence, Dust, Falling Material",
        "title_es": "Seguridad en Demolición — Secuencia, Polvo, Material que Cae",
        "why_en": (
            "Demolition is the most dangerous phase of any job. The "
            "structure was designed to stand up — every cut, every break, "
            "shifts loads in ways the original engineer didn't picture. "
            "The demo plan exists because eyeballing it kills people. We "
            "follow the plan, top down, no improvising."
        ),
        "why_es": (
            "La demolición es la fase más peligrosa del trabajo. La "
            "estructura fue diseñada para sostenerse — cada corte, cada "
            "rotura, mueve las cargas en formas que el ingeniero original "
            "no imaginó. El plan de demolición existe porque hacerlo a "
            "ojo mata gente. Seguimos el plan, de arriba para abajo, sin "
            "improvisar."
        ),
        "rules_en": [
            ("Engineering survey required before demolition begins.", "§3306.2"),
            ("Demolition plan filed with DOB; pre-construction meeting held.", "§3306.4"),
            ("Demolish top-down or per the filed sequence — never improvise.", "§3306.5"),
            ("Dust mitigation — water spray, screening, debris chutes.", "§3306.6"),
            ("Falling material protected — chutes, netting, or enclosed enclosures.", "§3306.6.2"),
        ],
        "rules_es": [
            ("Inspección de ingeniería requerida antes de empezar.", "§3306.2"),
            ("Plan de demolición presentado al DOB; reunión previa hecha.", "§3306.4"),
            ("Demoler de arriba a abajo o según la secuencia — nunca improvisar.", "§3306.5"),
            ("Mitigar polvo — aspersión de agua, malla, conductos de escombros.", "§3306.6"),
            ("Material que cae protegido — conductos, redes o encierros.", "§3306.6.2"),
        ],
        "do_en": [
            "Confirm the demo sequence with the foreman before swinging a hammer.",
            "Wet down the work area before and during cutting.",
            "Drop debris only into chutes — never over open edges.",
            "Watch for shifting loads when you cut a beam or strap.",
            "Stop if you see anything you didn't expect — call the engineer.",
        ],
        "do_es": [
            "Confirma la secuencia con el capataz antes de empezar.",
            "Moja el área antes y durante el corte.",
            "Tira escombros solo en conductos — nunca por bordes abiertos.",
            "Cuida cargas que se muevan cuando cortas una viga o correa.",
            "Para si ves algo que no esperabas — llama al ingeniero.",
        ],
        "dont_en": [
            "Don't change the demolition sequence on your own.",
            "Don't work below an active demo zone — clear it first.",
            "Don't dry-cut concrete or masonry without water control.",
            "Don't reuse a debris chute that shows cracking or wear.",
        ],
        "dont_es": [
            "No cambies la secuencia de demolición por tu cuenta.",
            "No trabajes debajo de una zona activa de demolición — despéjala primero.",
            "No cortes concreto o mampostería en seco sin control de agua.",
            "No reutilices un conducto agrietado o gastado.",
        ],
        "questions_en": [
            "What's today's demo sequence — show me where it's posted.",
            "Where does debris go from your station to the dumpster?",
            "If a wall shifted unexpectedly right now, what would you do first?",
        ],
        "questions_es": [
            "¿Cuál es la secuencia de hoy — muéstrame dónde está el plan?",
            "¿A dónde van los escombros de tu puesto al contenedor?",
            "Si una pared se moviera de repente, ¿qué harías primero?",
        ],
        "description": "Demolition — engineering survey, top-down sequence, dust mitigation, and protected debris paths.",
    },

    # ============================================================
    # Topic 15 — Powder-Actuated Tools
    # ============================================================
    {
        "topic_number": 15,
        "slug": "15-powder-actuated-tools",
        "category": "Demo",
        "ch33_ref": "§3311",
        "est_minutes": 15,
        "title_en": "Powder-Actuated Tools — Safe Use & Training",
        "title_es": "Herramientas de Pólvora — Uso Seguro y Capacitación",
        "why_en": (
            "A powder-actuated tool fires a fastener like a bullet — into "
            "concrete, into steel, sometimes into a worker on the other "
            "side of a wall. They are FDNY-permitted, training-restricted "
            "tools. Wrong load color, wrong fastener length, no eye "
            "protection — every one of those is a hospital trip."
        ),
        "why_es": (
            "Una herramienta de pólvora dispara un clavo como bala — al "
            "concreto, al acero, a veces a un trabajador del otro lado de "
            "la pared. Son herramientas permisadas por FDNY, con "
            "capacitación restringida. Color de carga equivocado, clavo "
            "muy largo, sin lentes — cada uno es una visita al hospital."
        ),
        "rules_en": [
            ("Operator licensed / certified by the tool manufacturer.", "§3311.2"),
            ("Tool inspected before each shift; defective tools tagged out.", "§3311.3"),
            ("Eye protection AND hearing protection required when firing.", "§3311.3 / OSHA"),
            ("Match load color (power level) to the substrate — never over-power.", "§3311.3"),
            ("Never fire through unsupported material or into a hollow wall.", "§3311.4"),
        ],
        "rules_es": [
            ("Operador con licencia / certificación del fabricante.", "§3311.2"),
            ("Inspeccionar herramienta antes de cada turno; defectuosa fuera de uso.", "§3311.3"),
            ("Lentes Y protección auditiva requeridos al disparar.", "§3311.3 / OSHA"),
            ("El color de la carga debe coincidir con el material — nunca sobre-potencia.", "§3311.3"),
            ("Nunca disparar a material sin soporte o a pared hueca.", "§3311.4"),
        ],
        "do_en": [
            "Show your certification card to the foreman before drawing the tool.",
            "Test fire the tool on a scrap of the actual substrate.",
            "Hold the tool perpendicular to the surface — 90 degrees only.",
            "Keep your hand AWAY from the muzzle — no pinch grip.",
            "Lock unused loads in the manufacturer's case, not your pocket.",
        ],
        "do_es": [
            "Muestra tu tarjeta de certificación al capataz antes de tomar la herramienta.",
            "Haz una prueba en un pedazo del mismo material.",
            "Sostén la herramienta perpendicular — solo a 90 grados.",
            "Mantén la mano LEJOS de la boca — no agarrar de pinza.",
            "Guarda cargas no usadas en la caja del fabricante, no en el bolsillo.",
        ],
        "dont_en": [
            "Don't use a powder-actuated tool without current certification.",
            "Don't fire toward a worker on the other side of the wall.",
            "Don't re-fire a misfire — wait 30 seconds, then unload.",
            "Don't carry loose powder loads in your tool belt or pocket.",
        ],
        "dont_es": [
            "No uses la herramienta sin certificación al día.",
            "No dispares hacia un trabajador del otro lado de la pared.",
            "No re-dispares una falla — espera 30 segundos y descarga.",
            "No cargues pólvora suelta en el cinturón ni en el bolsillo.",
        ],
        "questions_en": [
            "What's your current certification expiration date?",
            "What load color goes into hardened concrete vs. a hollow CMU?",
            "What do you do when the tool misfires?",
        ],
        "questions_es": [
            "¿Cuándo vence tu certificación actual?",
            "¿Qué color de carga va al concreto duro vs. CMU hueco?",
            "¿Qué haces cuando la herramienta falla en disparar?",
        ],
        "description": "Powder-actuated tools — certification, load colors, perpendicular firing, and the misfire procedure.",
    },
]

