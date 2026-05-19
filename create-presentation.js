const PptxGenJS = require("pptxgenjs");
const fs = require("fs");

const prs = new PptxGenJS();
prs.defineLayout({ name: 'LAYOUT1', width: 10, height: 7.5 });
prs.defineLayout({ name: 'BLANK', width: 10, height: 7.5 });

// Brand colors
const colors = {
  red: "#B11E2E",
  ink: "#14161C",
  cream: "#FAF7F1",
  white: "#FFFFFF",
  mute: "#76777E",
  lightGray: "#EEEEEE",
  green: "#4CAF50"
};

const fonts = {
  header: "Georgia",
  body: "Calibri"
};

// Helper functions
function addHeaderRule(slide, yPos = 0.35) {
  slide.addShape(prs.ShapeType.rect, {
    x: 0.5, y: yPos, w: 9, h: 0.1,
    fill: { color: colors.red },
    line: { type: "none" }
  });
}

function addEyebrow(slide, text, x = 0.5, y = 0.35) {
  slide.addText(text, {
    x: x, y: y, w: 9, h: 0.25,
    fontSize: 9, bold: true, color: colors.mute,
    fontFace: fonts.body,
    align: "left",
    letterSpacing: 2
  });
}

function addTitleDark(slide, text) {
  slide.addText(text, {
    x: 0.5, y: 1, w: 9, h: 1,
    fontSize: 40, bold: true, color: colors.white,
    fontFace: fonts.header,
    align: "left"
  });
}

function addTitleLight(slide, text) {
  slide.addText(text, {
    x: 0.5, y: 0.8, w: 9, h: 0.8,
    fontSize: 40, bold: true, color: colors.red,
    fontFace: fonts.header,
    align: "left"
  });
}

// ===== SLIDE 1: TITLE =====
let slide = prs.addSlide();
slide.background = { color: colors.ink };

// Red star centered
slide.addText("★", {
  x: 4.5, y: 1.5, w: 1, h: 1,
  fontSize: 100, color: colors.red,
  fontFace: fonts.header,
  align: "center"
});

// Wordmark
slide.addText("SUPERSTARS CONTRACTING", {
  x: 0.5, y: 2.7, w: 9, h: 0.6,
  fontSize: 32, bold: true, color: colors.white,
  fontFace: fonts.header,
  align: "center"
});

// Subtitle
slide.addText("Project Console", {
  x: 0.5, y: 3.35, w: 9, h: 0.4,
  fontSize: 24, italic: true, color: colors.red,
  fontFace: fonts.header,
  align: "center"
});

// Address
slide.addText("890 East 135th Street · 890 E 135th Street", {
  x: 0.5, y: 3.85, w: 9, h: 0.3,
  fontSize: 14, color: colors.white,
  fontFace: fonts.body,
  align: "center"
});

// Footer
slide.addText("Operational system overview · 2026", {
  x: 0.5, y: 4.4, w: 9, h: 0.25,
  fontSize: 12, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 2: THE PROBLEM =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "Where projects break down");

// Left column: pain points
const painPoints = [
  "Daily reports still typed by hand at 7 PM each night",
  "RFIs lost in email threads, response time untracked",
  "Scaffold drops not coordinated with billing milestones",
  "Compliance documents in folders no one finds when DOB inspects",
  "Foreman + office on different tools, different data"
];

let yPos = 1.5;
painPoints.forEach(point => {
  slide.addText("★", {
    x: 0.6, y: yPos, w: 0.2, h: 0.3,
    fontSize: 14, color: colors.red,
    fontFace: fonts.header,
    align: "center"
  });
  
  slide.addText(point, {
    x: 1.1, y: yPos, w: 3.9, h: 0.6,
    fontSize: 13, color: colors.ink,
    fontFace: fonts.body,
    align: "left"
  });
  
  yPos += 0.75;
});

// Right column: illustration placeholder
slide.addShape(prs.ShapeType.rect, {
  x: 5.2, y: 1.5, w: 4, h: 4,
  fill: { color: colors.white },
  line: { color: colors.ink, width: 2 }
});

slide.addText("📋 Before: Scattered Papers & Lost Data", {
  x: 5.3, y: 3.3, w: 3.8, h: 0.8,
  fontSize: 13, bold: true, color: colors.ink,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 3: THE SYSTEM =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "One system. Eight document types. Real distribution.");

// 3-column grid
const modules = [
  { title: "Documents", icon: "📄", items: "DCR · Weekly Summary\nLookahead · RFI · Site Closure\nMeeting Minutes\nToolbox Talks · Drop Plans" },
  { title: "Workflows", icon: "⚙️", items: "Auto-routing\nSLA tracking\nSign-off & Chain\nEmail distribution\nSendGrid integration" },
  { title: "Data", icon: "💾", items: "Employees & Permits\nDrawings & CD-5s\nCompliance logs\nDOB Codes catalog\nRECAP pipeline" }
];

const colWidth = 2.8;
let xPos = 0.8;

modules.forEach(mod => {
  slide.addShape(prs.ShapeType.rect, {
    x: xPos, y: 1.3, w: colWidth, h: 5,
    fill: { color: colors.white },
    line: { color: colors.red, width: 2 }
  });
  
  slide.addText(mod.icon, {
    x: xPos + 0.4, y: 1.6, w: colWidth - 0.8, h: 0.4,
    fontSize: 32, color: colors.red,
    fontFace: fonts.header,
    align: "center"
  });
  
  slide.addText(mod.title, {
    x: xPos + 0.4, y: 2.1, w: colWidth - 0.8, h: 0.3,
    fontSize: 14, bold: true, color: colors.ink,
    fontFace: fonts.header,
    align: "center"
  });
  
  slide.addText(mod.items, {
    x: xPos + 0.3, y: 2.5, w: colWidth - 0.6, h: 3,
    fontSize: 11, color: colors.ink,
    fontFace: fonts.body,
    align: "center",
    valign: "top"
  });
  
  xPos += colWidth + 0.4;
});

// ===== SLIDE 4: DAILY CONSTRUCTION REPORT =====
slide = prs.addSlide();
slide.background = { color: colors.ink };

addEyebrow(slide, "DOCUMENT 1 · DAILY", 0.5, 0.5);
addTitleDark(slide, "Daily Construction Report");

slide.addText("Generated · Distributed · Archived", {
  x: 0.5, y: 1.75, w: 9, h: 0.35,
  fontSize: 18, italic: true, color: colors.red,
  fontFace: fonts.header
});

// Big stats
const stats = [
  { label: "workers signed in", value: "10" },
  { label: "total hours", value: "82.25" },
  { label: "auto-emailed recipients", value: "9" }
];

let statX = 0.8;
stats.forEach(stat => {
  slide.addText(stat.value, {
    x: statX, y: 2.5, w: 2.8, h: 0.8,
    fontSize: 48, bold: true, color: colors.red,
    fontFace: fonts.header,
    align: "center"
  });
  
  slide.addText(stat.label, {
    x: statX, y: 3.4, w: 2.8, h: 0.3,
    fontSize: 11, color: colors.mute,
    fontFace: fonts.body,
    align: "center"
  });
  
  statX += 3;
});

// Bullets
yPos = 4.2;
const dcr_bullets = [
  "DCR auto-assembles at 6 PM from sign-ins + weather + zone logs",
  "9 emails fire to stakeholders automatically via SendGrid",
  "PDF archived to data room for project records"
];

dcr_bullets.forEach(bullet => {
  slide.addText("★", {
    x: 0.7, y: yPos, w: 0.2, h: 0.2,
    fontSize: 12, color: colors.red,
    fontFace: fonts.header
  });
  
  slide.addText(bullet, {
    x: 1.1, y: yPos, w: 8.4, h: 0.5,
    fontSize: 12, color: colors.white,
    fontFace: fonts.body
  });
  
  yPos += 0.6;
});

// ===== SLIDE 5: WEEKLY PROGRESS SUMMARY =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "Weekly Progress Summary");

slide.addText("EVERY FRIDAY 5 PM · DUAL-TRACK INTERNAL + CLIENT", {
  x: 0.5, y: 0.9, w: 9, h: 0.25,
  fontSize: 10, bold: true, color: colors.mute,
  fontFace: fonts.body,
  letterSpacing: 1.5
});

// Left column: Internal
slide.addShape(prs.ShapeType.rect, {
  x: 0.6, y: 1.4, w: 4.2, h: 5,
  fill: { color: colors.white },
  line: { color: colors.ink, width: 1 }
});

slide.addText("INTERNAL VERSION", {
  x: 0.8, y: 1.6, w: 3.8, h: 0.3,
  fontSize: 12, bold: true, color: colors.ink,
  fontFace: fonts.header
});

const internal = [
  "Full crew breakdown by trade",
  "Complete hours per person",
  "All incidents recorded",
  "Named workers & supervisors"
];

yPos = 2.1;
internal.forEach(item => {
  slide.addText("•", {
    x: 0.9, y: yPos, w: 0.2, h: 0.2,
    fontSize: 12, color: colors.red,
    fontFace: fonts.body
  });
  
  slide.addText(item, {
    x: 1.2, y: yPos, w: 3.5, h: 0.4,
    fontSize: 11, color: colors.ink,
    fontFace: fonts.body
  });
  
  yPos += 0.5;
});

// Right column: Client
slide.addShape(prs.ShapeType.rect, {
  x: 5.2, y: 1.4, w: 4.2, h: 5,
  fill: { color: colors.white },
  line: { color: colors.red, width: 2 }
});

slide.addText("CLIENT VERSION", {
  x: 5.4, y: 1.6, w: 3.8, h: 0.3,
  fontSize: 12, bold: true, color: colors.red,
  fontFace: fonts.header
});

const client = [
  "Trade counts only (no names)",
  "Redacted incident details",
  "Curated photos",
  "Progress metrics & milestones"
];

yPos = 2.1;
client.forEach(item => {
  slide.addText("•", {
    x: 5.3, y: yPos, w: 0.2, h: 0.2,
    fontSize: 12, color: colors.red,
    fontFace: fonts.body
  });
  
  slide.addText(item, {
    x: 5.6, y: yPos, w: 3.8, h: 0.4,
    fontSize: 11, color: colors.ink,
    fontFace: fonts.body
  });
  
  yPos += 0.5;
});

// Callout
slide.addShape(prs.ShapeType.rect, {
  x: 0.6, y: 6.7, w: 8.8, h: 0.5,
  fill: { color: colors.red },
  line: { type: "none" }
});

slide.addText("Same data → two different audiences → automatically", {
  x: 0.8, y: 6.8, w: 8.4, h: 0.3,
  fontSize: 12, bold: true, color: colors.white,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 6: 2-WEEK LOOK AHEAD =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "Two-Week Look Ahead");

slide.addText("Generated for the Thursday weekly meeting", {
  x: 0.5, y: 0.9, w: 9, h: 0.25,
  fontSize: 11, italic: true, color: colors.mute,
  fontFace: fonts.body
});

// Gantt visualization
const days = ["M", "T", "W", "T", "F", "S", "S", "M", "T", "W", "T", "F", "S", "S"];
const cellWidth = 0.6;
let xStart = 0.7;

// Day headers
days.forEach((day, idx) => {
  const isWeekend = (idx + 1) % 7 === 6 || (idx + 1) % 7 === 0;
  slide.addText(day, {
    x: xStart + (idx * cellWidth), y: 1.5, w: cellWidth, h: 0.25,
    fontSize: 9, bold: true, color: colors.ink,
    fontFace: fonts.header,
    align: "center"
  });
});

// Activity bars (simplified representation)
const activities = [
  { name: "Foundation work", start: 0, length: 5, color: colors.ink, y: 2.1 },
  { name: "Scaffolding", start: 4, length: 3, color: colors.red, y: 2.8 },
  { name: "DOB Inspection", start: 6, length: 1, color: "#FFB84D", y: 3.5 },
  { name: "Material delivery", start: 7, length: 4, color: "#FFB84D", y: 4.2 }
];

activities.forEach(act => {
  slide.addShape(prs.ShapeType.rect, {
    x: xStart + (act.start * cellWidth), y: act.y, w: (act.length * cellWidth), h: 0.35,
    fill: { color: act.color },
    line: { type: "none" }
  });
  
  slide.addText(act.name, {
    x: 0.7, y: act.y, w: xStart - 0.7, h: 0.35,
    fontSize: 10, bold: true, color: colors.ink,
    fontFace: fonts.body,
    align: "right",
    valign: "middle"
  });
});

// Key bullets
yPos = 5.2;
const lookahead_bullets = [
  "14-day rolling window with weekend indicators",
  "Color-coded activities: Work (dark), Inspection (gold), Delivery (gold)",
  "Updated weekly based on RFI resolutions & change orders"
];

lookahead_bullets.forEach(bullet => {
  slide.addText("★", {
    x: 0.7, y: yPos, w: 0.2, h: 0.2,
    fontSize: 12, color: colors.red,
    fontFace: fonts.header
  });
  
  slide.addText(bullet, {
    x: 1.1, y: yPos, w: 8.4, h: 0.4,
    fontSize: 11, color: colors.ink,
    fontFace: fonts.body
  });
  
  yPos += 0.5;
});

// ===== SLIDE 7: RFI WORKFLOW =====
slide = prs.addSlide();
slide.background = { color: colors.ink };

addEyebrow(slide, "WORKFLOW · LIVE", 0.5, 0.5);
addTitleDark(slide, "RFI Submission → Routing → Distribution");

// Process diagram with arrows
const steps = [
  { label: "Submit", detail: "mobile-first form", x: 0.8 },
  { label: "Auto-route", detail: "priority rules", x: 2.8 },
  { label: "PDF + Email", detail: "SendGrid", x: 4.8 },
  { label: "Track", detail: "SLA + status", x: 6.8 }
];

steps.forEach((step, idx) => {
  // Circle background
  slide.addShape(prs.ShapeType.ellipse, {
    x: step.x, y: 2.2, w: 0.8, h: 0.8,
    fill: { color: colors.red },
    line: { type: "none" }
  });
  
  // Step number
  slide.addText((idx + 1).toString(), {
    x: step.x, y: 2.2, w: 0.8, h: 0.8,
    fontSize: 28, bold: true, color: colors.white,
    fontFace: fonts.header,
    align: "center",
    valign: "middle"
  });
  
  // Labels
  slide.addText(step.label, {
    x: step.x, y: 3.15, w: 0.8, h: 0.25,
    fontSize: 11, bold: true, color: colors.white,
    fontFace: fonts.header,
    align: "center"
  });
  
  slide.addText(step.detail, {
    x: step.x, y: 3.45, w: 0.8, h: 0.25,
    fontSize: 9, color: colors.mute,
    fontFace: fonts.body,
    align: "center"
  });
  
  // Arrow (except after last step)
  if (idx < steps.length - 1) {
    slide.addShape(prs.ShapeType.triangle, {
      x: step.x + 0.9, y: 2.55, w: 0.35, h: 0.3,
      fill: { color: colors.red },
      line: { type: "none" },
      rotate: 90
    });
  }
});

// Big stat
slide.addText("9 emails dispatched in 2.3 seconds", {
  x: 0.5, y: 4.5, w: 9, h: 0.5,
  fontSize: 28, bold: true, color: colors.red,
  fontFace: fonts.header,
  align: "center"
});

slide.addText("verified live test, May 5", {
  x: 0.5, y: 5.1, w: 9, h: 0.25,
  fontSize: 11, color: colors.mute,
  fontFace: fonts.body,
  align: "center",
  italic: true
});

// ===== SLIDE 8: SITE CLOSURE =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "Site Closure Checklist");

slide.addText("Foreman daily · 24 items · 9 sections · Art-storage tuned", {
  x: 0.5, y: 0.9, w: 9, h: 0.25,
  fontSize: 11, italic: true, color: colors.mute,
  fontFace: fonts.body
});

// 3x3 grid
const sections = [
  "Personnel", "Equipment", "Hot Work / Fire",
  "Dust & Debris", "Water Intrusion", "Site Security",
  "Building Integrity", "Climate Control", "Documentation"
];

const gridSize = 2.8;
let gridX = 0.6;
let gridY = 1.4;

sections.forEach((section, idx) => {
  if (idx > 0 && idx % 3 === 0) {
    gridY += gridSize + 0.3;
    gridX = 0.6;
  }
  
  slide.addShape(prs.ShapeType.rect, {
    x: gridX, y: gridY, w: gridSize, h: gridSize,
    fill: { color: colors.white },
    line: { color: colors.red, width: 2 }
  });
  
  slide.addText(section, {
    x: gridX + 0.15, y: gridY + 1.2, w: gridSize - 0.3, h: 0.8,
    fontSize: 13, bold: true, color: colors.ink,
    fontFace: fonts.header,
    align: "center",
    valign: "middle"
  });
  
  gridX += gridSize + 0.3;
});

slide.addText("Archived locally for project records. Not distributed.", {
  x: 0.5, y: 6.8, w: 9, h: 0.3,
  fontSize: 11, italic: true, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 9: TOOLBOX TALKS =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "Toolbox Talk Library");

slide.addText("25 DOB + OSHA-aligned topics · Generate handout in seconds", {
  x: 0.5, y: 0.9, w: 9, h: 0.25,
  fontSize: 11, italic: true, color: colors.mute,
  fontFace: fonts.body
});

// Horizontal bars
const talks = [
  { label: "Fall Protection", count: 4 },
  { label: "Scaffold", count: 3 },
  { label: "PPE", count: 2 },
  { label: "Hot Work", count: 2 },
  { label: "Hazard Comm", count: 3 },
  { label: "Material Handling", count: 2 },
  { label: "Equipment", count: 2 },
  { label: "Site Conditions", count: 3 },
  { label: "Emergency", count: 2 }
];

yPos = 1.5;
const maxWidth = 3;

talks.forEach(talk => {
  // Label
  slide.addText(talk.label, {
    x: 0.6, y: yPos, w: 2, h: 0.3,
    fontSize: 10, bold: true, color: colors.ink,
    fontFace: fonts.body,
    align: "right"
  });
  
  // Bar background
  slide.addShape(prs.ShapeType.rect, {
    x: 2.8, y: yPos + 0.05, w: maxWidth, h: 0.2,
    fill: { color: colors.lightGray },
    line: { type: "none" }
  });
  
  // Bar fill (proportional to count, max 4)
  const barWidth = (talk.count / 4) * maxWidth;
  slide.addShape(prs.ShapeType.rect, {
    x: 2.8, y: yPos + 0.05, w: barWidth, h: 0.2,
    fill: { color: colors.red },
    line: { type: "none" }
  });
  
  // Count
  slide.addText(talk.count.toString(), {
    x: 5.9, y: yPos, w: 0.3, h: 0.3,
    fontSize: 10, bold: true, color: colors.red,
    fontFace: fonts.header
  });
  
  yPos += 0.45;
});

slide.addText("Sign-in sheet built in. DOB-ready audit trail.", {
  x: 0.5, y: 6.8, w: 9, h: 0.3,
  fontSize: 11, italic: true, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 10: DROP PLAN MANAGEMENT =====
slide = prs.addSlide();
slide.background = { color: colors.ink };

addEyebrow(slide, "OPERATIONAL CORE", 0.5, 0.5);
addTitleDark(slide, "Drop Plan Management");

slide.addText("Scaffold sequencing · Sign-off workflow · Sign-off chain", {
  x: 0.5, y: 1.75, w: 9, h: 0.35,
  fontSize: 16, italic: true, color: colors.red,
  fontFace: fonts.header
});

// Building elevation with zones
const zoneColors = [colors.red, colors.white, colors.white, colors.white, colors.white, colors.white, colors.white, colors.green];
const zoneLabels = ["1\nActive", "2\nPlanned", "3\nPlanned", "4\nPlanned", "5\nPlanned", "6\nPlanned", "7\nPlanned", "8\nDone"];

const buildingX = 1.5;
const buildingY = 2.5;
const zoneW = 1;
const zoneH = 0.9;

zoneLabels.forEach((label, idx) => {
  const col = idx % 4;
  const row = Math.floor(idx / 4);
  const x = buildingX + (col * zoneW);
  const y = buildingY + (row * zoneH);
  
  slide.addShape(prs.ShapeType.rect, {
    x: x, y: y, w: zoneW - 0.05, h: zoneH - 0.05,
    fill: { color: zoneColors[idx] },
    line: { color: colors.white, width: 1 }
  });
  
  const textColor = idx === 0 || idx === 7 ? colors.ink : colors.white;
  slide.addText(label, {
    x: x, y: y, w: zoneW - 0.05, h: zoneH - 0.05,
    fontSize: 9, bold: true, color: textColor,
    fontFace: fonts.header,
    align: "center",
    valign: "middle"
  });
});

// Legend
slide.addShape(prs.ShapeType.rect, {
  x: 1.5, y: 4.7, w: 0.3, h: 0.3,
  fill: { color: colors.red }
});
slide.addText("Active", {
  x: 1.95, y: 4.7, w: 1.2, h: 0.3,
  fontSize: 10, color: colors.white,
  fontFace: fonts.body
});

slide.addShape(prs.ShapeType.rect, {
  x: 3.3, y: 4.7, w: 0.3, h: 0.3,
  fill: { color: colors.white },
  line: { color: colors.white, width: 1 }
});
slide.addText("Planned", {
  x: 3.75, y: 4.7, w: 1.2, h: 0.3,
  fontSize: 10, color: colors.white,
  fontFace: fonts.body
});

slide.addShape(prs.ShapeType.rect, {
  x: 5.1, y: 4.7, w: 0.3, h: 0.3,
  fill: { color: colors.green }
});
slide.addText("Signed Off", {
  x: 5.55, y: 4.7, w: 1.5, h: 0.3,
  fontSize: 10, color: colors.white,
  fontFace: fonts.body
});

// Signature chain
slide.addText("Foreman → Super → QEI → Owner Rep · Photo-gated · Sequence-locked", {
  x: 0.5, y: 5.5, w: 9, h: 0.4,
  fontSize: 12, bold: true, color: colors.white,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 11: COMPLIANCE & DATA ROOM =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "Compliance & Data Room");

// Left column: VISIBLE
slide.addShape(prs.ShapeType.rect, {
  x: 0.6, y: 1.3, w: 4.2, h: 5,
  fill: { color: colors.white },
  line: { color: colors.ink, width: 1 }
});

slide.addText("VISIBLE", {
  x: 0.8, y: 1.55, w: 3.8, h: 0.3,
  fontSize: 13, bold: true, color: colors.ink,
  fontFace: fonts.header
});

const visible_items = [
  { label: "Permits tracker", detail: "5 active · 1 expiring" },
  { label: "FISP panel", detail: "status & docs" },
  { label: "Renewal pipeline", detail: "30-day outlook" }
];

yPos = 2.1;
visible_items.forEach(item => {
  slide.addText(item.label, {
    x: 0.9, y: yPos, w: 3.6, h: 0.25,
    fontSize: 11, bold: true, color: colors.red,
    fontFace: fonts.header
  });
  
  slide.addText(item.detail, {
    x: 0.9, y: yPos + 0.3, w: 3.6, h: 0.25,
    fontSize: 10, color: colors.mute,
    fontFace: fonts.body
  });
  
  yPos += 0.8;
});

// Right column: BACKEND
slide.addShape(prs.ShapeType.rect, {
  x: 5.2, y: 1.3, w: 4.2, h: 5,
  fill: { color: colors.white },
  line: { color: colors.red, width: 2 }
});

slide.addText("BACKEND", {
  x: 5.4, y: 1.55, w: 3.8, h: 0.3,
  fontSize: 13, bold: true, color: colors.red,
  fontFace: fonts.header
});

const backend_items = [
  { label: "DOB Codes catalog", detail: "Ch. 33, LL11/FISP, RCNY" },
  { label: "Drawings", detail: "project + historical" },
  { label: "CD-5 approvals", detail: "indexed & tracked" }
];

yPos = 2.1;
backend_items.forEach(item => {
  slide.addText(item.label, {
    x: 5.4, y: yPos, w: 3.6, h: 0.25,
    fontSize: 11, bold: true, color: colors.red,
    fontFace: fonts.header
  });
  
  slide.addText(item.detail, {
    x: 5.4, y: yPos + 0.3, w: 3.6, h: 0.25,
    fontSize: 10, color: colors.mute,
    fontFace: fonts.body
  });
  
  yPos += 0.8;
});

slide.addText("We surface what matters, archive what's required.", {
  x: 0.5, y: 6.8, w: 9, h: 0.3,
  fontSize: 11, italic: true, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 12: LIVE INTEGRATION =====
slide = prs.addSlide();
slide.background = { color: colors.ink };

addEyebrow(slide, "PROVEN END TO END", 0.5, 0.5);
addTitleDark(slide, "Email distribution live as of May 5, 2026");

// Big stat
slide.addText("9/9", {
  x: 3.5, y: 1.8, w: 3, h: 1,
  fontSize: 72, bold: true, color: colors.red,
  fontFace: fonts.header,
  align: "center"
});

slide.addText("RFI test emails sent successfully via SendGrid", {
  x: 0.5, y: 2.9, w: 9, h: 0.3,
  fontSize: 12, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// Integration status
const integrations = [
  { name: "SendGrid (Email)", status: "Connected", color: colors.green, x: 1.5 },
  { name: "Twilio (SMS)", status: "Pending", color: colors.mute, x: 4 },
  { name: "Anthropic Claude (AI Notes)", status: "Pending", color: colors.mute, x: 6.5 }
];

yPos = 4;
integrations.forEach(integ => {
  slide.addShape(prs.ShapeType.ellipse, {
    x: integ.x, y: yPos, w: 0.4, h: 0.4,
    fill: { color: integ.color },
    line: { type: "none" }
  });
  
  slide.addText("★", {
    x: integ.x + 0.05, y: yPos + 0.05, w: 0.3, h: 0.3,
    fontSize: 16, color: colors.white,
    fontFace: fonts.header,
    align: "center",
    valign: "middle"
  });
  
  slide.addText(integ.name, {
    x: integ.x + 0.5, y: yPos, w: 1.8, h: 0.2,
    fontSize: 10, bold: true, color: colors.white,
    fontFace: fonts.body
  });
  
  slide.addText(integ.status, {
    x: integ.x + 0.5, y: yPos + 0.22, w: 1.8, h: 0.15,
    fontSize: 9, color: colors.mute,
    fontFace: fonts.body
  });
});

slide.addText("One API key away from full automation.", {
  x: 0.5, y: 5.8, w: 9, h: 0.3,
  fontSize: 12, italic: true, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 13: ROADMAP =====
slide = prs.addSlide();
slide.background = { color: colors.cream };

addHeaderRule(slide, 0.35);
addTitleLight(slide, "Where we go from here");

// Swimlanes
const roadmapItems = [
  { week: "Week 1", task: "Database + API server", status: "DONE", y: 1.5 },
  { week: "Week 2", task: "Live dashboard reads", status: "DONE", y: 2.6 },
  { week: "Week 3", task: "Foreman mobile entry layer", status: "NEXT", y: 3.7 },
  { week: "Week 4", task: "Pilot launch on Bronx site", status: "COMING", y: 4.8 }
];

roadmapItems.forEach(item => {
  // Week label
  slide.addText(item.week, {
    x: 0.6, y: item.y, w: 0.9, h: 0.35,
    fontSize: 10, bold: true, color: colors.mute,
    fontFace: fonts.body,
    align: "right"
  });
  
  // Task box
  const statusColor = item.status === "DONE" ? colors.green : (item.status === "NEXT" ? colors.red : colors.lightGray);
  const statusTextColor = item.status === "DONE" || item.status === "NEXT" ? colors.white : colors.mute;
  
  slide.addShape(prs.ShapeType.rect, {
    x: 1.7, y: item.y, w: 4.5, h: 0.35,
    fill: { color: statusColor },
    line: { type: "none" }
  });
  
  slide.addText(item.task, {
    x: 1.9, y: item.y, w: 4.1, h: 0.35,
    fontSize: 11, bold: true, color: statusTextColor,
    fontFace: fonts.body,
    valign: "middle"
  });
  
  // Status badge
  slide.addShape(prs.ShapeType.rect, {
    x: 6.5, y: item.y + 0.05, w: 1.2, h: 0.25,
    fill: { color: colors.white },
    line: { color: statusColor, width: 1 }
  });
  
  slide.addText(item.status, {
    x: 6.5, y: item.y + 0.05, w: 1.2, h: 0.25,
    fontSize: 9, bold: true, color: statusColor,
    fontFace: fonts.header,
    align: "center",
    valign: "middle"
  });
});

slide.addText("Multi-site rollout · Q3 2026", {
  x: 0.5, y: 6.8, w: 9, h: 0.3,
  fontSize: 11, italic: true, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// ===== SLIDE 14: CLOSING =====
slide = prs.addSlide();
slide.background = { color: colors.ink };

// Red star
slide.addText("★", {
  x: 4.5, y: 1.5, w: 1, h: 1,
  fontSize: 100, color: colors.red,
  fontFace: fonts.header,
  align: "center"
});

// Main message
slide.addText("Built for facade work. Built for the field.", {
  x: 0.5, y: 2.8, w: 9, h: 0.8,
  fontSize: 32, italic: true, color: colors.white,
  fontFace: fonts.header,
  align: "center"
});

// Subtitle
slide.addText("Superstars Contracting · Project Console", {
  x: 0.5, y: 3.8, w: 9, h: 0.4,
  fontSize: 16, color: colors.cream,
  fontFace: fonts.body,
  align: "center"
});

// Footer
slide.addText("Demo data shown. Bronx project deployment ready.", {
  x: 0.5, y: 6.8, w: 9, h: 0.25,
  fontSize: 9, color: colors.mute,
  fontFace: fonts.body,
  align: "center"
});

// Save to file
prs.writeFile({ fileName: "Superstars-Project-Console-Presentation.pptx" }).then(() => {
  console.log("Presentation saved successfully.");
  process.exit(0);
}).catch(err => {
  console.error("Error saving presentation:", err);
  process.exit(1);
});
