/**
 * D3.js collapsible taxonomy tree.
 * Renders a horizontal left-to-right tree; nodes expand lazily on click.
 * Vertical scroll via CSS overflow; zoom via Ctrl+scroll; pan via drag.
 */
import * as d3 from 'd3';
import { CLASS_DESCRIPTIONS } from './class_descriptions.js';
import { ORDER_DESCRIPTIONS } from './order_descriptions.js';
import { UPPER_DESCRIPTIONS } from './upper_descriptions.js';
import { OTHER_ORDER_DESCRIPTIONS } from './order_descriptions_other.js';

// Same origin when FastAPI serves the page (any port); :8000 fallback for file:// pages.
const API = window.location.protocol.startsWith('http') ? window.location.origin : 'http://localhost:8000';

export const RANK_COLOR = {
  domain:  '#e84393',
  kingdom: '#e74c3c',
  phylum:  '#e67e22',
  class:   '#f39c12',
  order:   '#27ae60',
  family:  '#3498db',
  genus:   '#b07cc6',
  species: '#16a085',
};

const NO_RANK_COLOR = '#9ca3af';
const DOT_CENTRE    = '#111827';   // page-dark: centre of a ring, outline of a filled dot
const SELECTED_FILL = '#f59e0b';

/**
 * Fill and outline of a node's dot. A closed node whose branches were loaded
 * (or a search path showing one branch) keeps its rank colour as a ring.
 * Muted nodes (letter groups, placeholders) are handled by the caller.
 */
export function nodeDot(data, selectedId) {
  const color = RANK_COLOR[data.rank] || NO_RANK_COLOR;
  if (data.node_id === selectedId) return { fill: SELECTED_FILL, stroke: '#fbbf24', width: 3 };
  if (data._children || data._pathOnly) return { fill: DOT_CENTRE, stroke: color, width: 2 };
  return { fill: color, stroke: DOT_CENTRE, width: 1.5 };
}

const _LEGEND_RANKS = ['domain', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'];

/** Fill `el` with the colour key: one row per rank, then grey, ring and selected. */
export function renderLegend(el) {
  const dot = ({ fill, stroke, width }) =>
    `<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="${fill}" stroke="${stroke}" stroke-width="${width}"/></svg>`;
  const row = (style, label) => `<li class="flex items-center gap-1.5">${dot(style)}<span>${label}</span></li>`;
  const rows = _LEGEND_RANKS.map(r =>
    row({ fill: RANK_COLOR[r], stroke: DOT_CENTRE, width: 1.5 }, r[0].toUpperCase() + r.slice(1)));
  rows.push(row({ fill: NO_RANK_COLOR, stroke: DOT_CENTRE, width: 1.5 }, 'Other rank'));
  rows.push(row({ fill: DOT_CENTRE, stroke: RANK_COLOR.order, width: 2 }, 'Closed, opened before'));
  rows.push(row({ fill: SELECTED_FILL, stroke: '#fbbf24', width: 2 }, 'Selected'));
  el.innerHTML = `<ul class="space-y-0.5">${rows.join('')}</ul>`;
}

const DX = 22;    // vertical px between sibling nodes
const DY = 250;   // horizontal px per depth level
const PAD = 48;   // top/bottom padding inside SVG

// Domains are looked up by rank too: Bacteria and Archaea are also animal genera.
const _DOMAIN_DESCRIPTIONS = {
  bacteria: 'Single-celled organisms without a nucleus, usually with peptidoglycan in their cell walls; one of the three domains of life, found almost everywhere on Earth.',
  archaea:  'Single-celled organisms without a nucleus that resemble bacteria but differ in their membranes and molecular machinery; one of the three domains of life, found in extreme environments as well as soils and oceans.',
  eukarya:  'All organisms whose cells have a nucleus, including animals, plants, fungi and many single-celled groups; one of the three domains of life.',
};

// Hover descriptions for animal phyla (major and minor).
// Keys are lowercase scientific names; values are one-sentence descriptions.
const _TAXON_DESCRIPTIONS = {
  viruses:         'Viruses are not part of any domain: they have no cells of their own and can only reproduce inside a host cell.',

  // Major phyla
  arthropoda:      'The largest animal phylum — invertebrates with jointed legs and a hard chitin exoskeleton (e.g. insects, spiders, crabs, centipedes).',
  chordata:        'Animals that possess a backbone or nerve cord at some point in their lifecycle (e.g. mammals, birds, reptiles, amphibians, fish).',
  mollusca:        'Soft-bodied animals, many of which secrete a protective calcium shell (e.g. snails, clams, octopuses, squids).',
  nematoda:        'Commonly known as roundworms — unsegmented, cylindrical worms found in nearly every environment, many of which are parasitic.',
  annelida:        'Segmented worms with ring-like body divisions (e.g. earthworms, leeches, marine bristle worms).',
  platyhelminthes: 'Flatworms with unsegmented, ribbon-like bodies lacking a respiratory or circulatory system (e.g. tapeworms, planarians).',
  cnidaria:        'Aquatic, radially symmetrical animals armed with specialised stinging cells called cnidocytes (e.g. jellyfish, corals, sea anemones).',
  echinodermata:   'Marine animals with spiny skin, radial symmetry, and a water-vascular system (e.g. sea stars, sea urchins, sand dollars).',
  porifera:        'The simplest multicellular animals — sponges that lack true organs and filter food from water currents.',
  // Minor phyla
  acanthocephala:  'Parasitic spiny-headed worms.',
  acoelomorpha:    'Tiny, simple, soft-bodied marine animals lacking a gut cavity.',
  brachiopoda:     'Marine lamp shells that resemble clams but are structurally distinct.',
  bryozoa:         'Microscopic, colonial aquatic "moss animals".',
  ectoprocta:      'Microscopic, colonial aquatic "moss animals" (also known as Bryozoa).',
  chaetognatha:    'Predatory marine arrow worms.',
  ctenophora:      'Translucent, non-stinging comb jellies.',
  cycliophora:     'Microscopic organisms found exclusively on the mouthparts of lobsters.',
  entoprocta:      'Tiny, sessile aquatic animals with goblet-shaped bodies.',
  gastrotricha:    'Microscopic, hairy-backed worms living in aquatic sediments.',
  gnathostomulida: 'Slender "jaw worms" that live between marine sand grains.',
  hemichordata:    'Marine acorn worms, evolutionarily close to chordates.',
  kinorhyncha:     'Microscopic, segmented "mud dragons".',
  loricifera:      'Microscopic sediment-dwellers encased in a protective armour shell (lorica).',
  micrognathozoa:  'Extremely tiny jawed animals native to Greenland springs.',
  nematomorpha:    'Horsehair worms — parasitic inside arthropods as larvae.',
  nemertea:        'Highly elastic ribbon worms.',
  onychophora:     'Velvet worms that look like caterpillars with stubby legs.',
  orthonectida:    'Microscopic parasites of marine invertebrates.',
  rhombozoa:       'Microscopic parasites of marine invertebrates.',
  phoronida:       'Marine horseshoe worms that live in upright chitin tubes.',
  placozoa:        'Simple, plate-like microscopic organisms with only a few cell layers.',
  priapulida:      'Unsegmented marine "penis worms" living in ocean sediments.',
  rotifera:        'Microscopic "wheel animals" with a rotating crown of cilia.',
  tardigrada:      'Near-indestructible microscopic "water bears" — can survive extreme conditions.',
  xenacoelomorpha: 'Primitive worm-like marine organisms combining xenoturbellids and acoels.',

  // ── Plant kingdom ──────────────────────────────────────────────────────────
  // True land plants (Embryophytes)
  tracheophyta:       'All vascular plants — those with water- and nutrient-conducting tissues (ferns, conifers, flowering plants).',
  bryophyta:          'Non-vascular land plants commonly known as mosses — low-growing and dependent on moist environments for reproduction.',
  marchantiophyta:    'Non-vascular land plants known as liverworts — flat, ribbon-like or leafy plants found in damp habitats.',
  hepaticophyta:      'Non-vascular land plants known as liverworts — flat, ribbon-like or leafy plants found in damp habitats.',
  anthocerotophyta:   'Non-vascular land plants known as hornworts — characterised by their distinctive horn-shaped sporophytes.',

  // Algal ancestors & relatives
  charophyta:         'Green algae including the stoneworts (brittleworts) — the closest living algal relatives of all land plants.',
  chlorophyta:        'The core green algae — a diverse group of mostly single-celled and filamentous algae, sister to the lineage that gave rise to land plants.',
  rhodophyta:         'Red algae — primarily marine, including many notable seaweeds; one of the oldest lineages of eukaryotic algae.',
  glaucophyta:        'A rare group of microscopic freshwater algae that retain unusually primitive chloroplast features, offering a window into early plant evolution.',
  glaucocystophyta:   'A rare group of microscopic freshwater algae that retain unusually primitive chloroplast features, offering a window into early plant evolution.',

  // Extinct fossil lineages
  langiophytophyta:   'A fossil phylum of extinct non-vascular Devonian land plants, including the famous Aglaophyton major from the Rhynie chert.',

  // ── Archaea domain ────────────────────────────────────────────────────────
  altiarchaeota:      'Subsurface, anaerobic microbes that form biofilms using unique grappling-hook-like appendages called "hami" to anchor themselves.',
  altarchaeota:       'Subsurface, anaerobic microbes that form biofilms using unique grappling-hook-like appendages called "hami" to anchor themselves.',
  methanobacteriota:  'A major group of methanogenic archaea that generate methane gas in anoxic environments like wetlands and animal digestive tracts.',
  halobacteriota:     'Salt-loving (halophilic) microbes that thrive in highly saline environments like salt flats and use specialised pigments to harvest light.',
  huberarchaeota:     'Ultra-small nanosized microbes found in deep terrestrial aquifers that live as dependent symbionts alongside other microbes.',
  thermoplasmatota:   'Acid-loving and heat-tolerant organisms, many of which lack a rigid cell wall and can dynamically change shape.',
  undinarchaeota:     'A poorly understood, uncultured marine lineage primarily identified via environmental DNA sequencing in deep ocean sediments.',
  micrarchaeota:      'Part of the DPANN supergroup — ultra-small cells with highly reduced genomes that typically live as parasites or symbionts on other archaea.',
  asgardarchaeota:    'The closest living prokaryotic relatives of eukaryotes, containing "eukaryotic signature proteins" that shed light on how complex cellular life evolved.',
  promethearchaeota: 'The closest living prokaryotic relatives of eukaryotes, containing "eukaryotic signature proteins" that shed light on how complex cellular life evolved.',
  nanoarchaeota:      'Tiny hyperthermophiles represented by Nanoarchaeum equitans, which survives exclusively by latching onto a host cell at marine hot vents.',
  nanobdellota: 'Tiny hyperthermophiles represented by Nanoarchaeum equitans, which survives exclusively by latching onto a host cell at marine hot vents.',
  crenarchaeota:      'An ancient lineage (TACK superphylum) famous for sulfur-metabolising microbes in boiling sulfur springs; also encompasses the former "Eocytes".',
  iainarchaeota:      'A DPANN phylum of small, uncultivated cells with limited metabolic capabilities, found in groundwater systems.',
  nanohaloarchaeota:  'Nanosized, salt-tolerant organisms that interact directly with larger halophilic host cells in hypersaline waters.',
  aenigmatarchaeota:  'Small-celled subsurface organisms found in hydrothermal environments with minimal independent metabolic pathways.',
  hadarchaeota:       'Deep subterranean microbes (formerly Hadesarchaeota) capable of metabolising toxic carbon monoxide in the absence of oxygen.',
  hydrothermarchaeota:'Archaea first recovered from hydrothermal vents on the Juan de Fuca Ridge, typically in marine environments high in iron and sulfur.',

  // ── Bacteria domain — core environmental & specialised phyla ──────────────
  methylomirabilota:  'Anaerobic microbes that generate their own oxygen internally to break down methane gas.',
  abyssubacteria:     'Deep subterranean microbes adapted to permanently dark, oxygen-starved environments.',
  nitrospirota:       'Soil and aquatic bacteria critical for converting nitrite into nitrate in the global nitrogen cycle.',
  fibrobacterota:     'Gut microbes essential for digesting plant cellulose inside grazing animals.',
  caldisericota:      'Heat-loving, anaerobic bacteria found in the depths of geothermal hot springs.',
  bdellovibrionota:   'Predatory bacteria that actively hunt, bore into, and consume other bacteria.',
  campylobacterota:   'Spiral-shaped bacteria that include both vital deep-sea carbon fixers and common foodborne pathogens.',
  thermodesulfobiota: 'A deeply branching bacterial lineage of heat-loving sulfate-reducers, with only two described species.',
  poribacteria:       'Specialised symbiotic bacteria found living almost exclusively inside marine sea sponges.',
  dictyoglomota:      'Extreme heat-dwellers that excel at breaking down complex plant starches.',
  dictyoglomerota: 'Extreme heat-dwellers that excel at breaking down complex plant starches.',
  planctomycetota:    'Unique aquatic bacteria that replicate by budding and possess complex internal membrane systems.',
  cloacimonadota:     'Anaerobic organisms commonly found in municipal and engineered wastewater treatment facilities.',
  deferribacterota:   'Aquatic bacteria that generate energy by reducing iron or manganese compounds.',
  aquificota:         'Deeply branching hyperthermophiles that use hydrogen to fuel life in boiling volcanic springs.',
  myxococcota:        'Social predatory bacteria that travel in coordinated swarms and build elaborate fruiting bodies.',
  verrucomicrobiota:  'Highly abundant soil and water microbes recognisable by distinctive warty bumps on their cell surface.',
  fusobacteriota:     'Slender, anaerobic bacteria inhabiting the oral and intestinal tracts of animals.',
  acidobacteriota:    'Acid-tolerant microbes that make up a large percentage of healthy forest soil communities.',

  // Dominant global lineages
  firmicutes:         'A massive phylum of Gram-positive microbes including vital gut bacteria, dairy fermenters, and resilient spore-formers.',
  bacillota:          'A massive phylum of Gram-positive microbes including vital gut bacteria, dairy fermenters, and resilient spore-formers.',
  proteobacteria:     'The largest and most diverse bacterial phylum, encompassing E. coli, nitrogen-fixers, and photosynthetic microbes.',
  pseudomonadota:     'The largest and most diverse bacterial phylum, encompassing E. coli, nitrogen-fixers, and photosynthetic microbes.',
  chlamydiota:        'Strict intracellular parasites that must live inside a host cell and cannot replicate independently.',
  bacteroidota:       'Gram-negative bacteria widespread in soil, sediments and sea water and abundant in animal guts, where they break down proteins and complex sugars.',
  desulfobacterota:   'Anaerobic bacteria, many of them sulfate-reducers; others reduce iron or generate electric current, and the group includes filamentous cable bacteria.',
  spirochaetota:      'Bacteria with long, corkscrew-shaped cells that move by twisting, using flagella housed between their two membranes.',
  thermoproteota:     'Archaea first known as heat-loving, sulfur-dependent extremophiles, some growing at up to 113 °C; marine members may be the most abundant archaea in the sea.',
  ochrophyta:         'Photosynthetic stramenopile algae with chloroplasts of red-algal origin, among the most diverse eukaryote lineages (e.g. brown algae, diatoms).',
  dicyemida:          'Tiny parasites that live in the renal appendages of cephalopods (also known as Rhombozoa).',
  sipuncula:          'Peanut worms — unsegmented marine worms, most burrowing in shallow sand and mud, with a retractable front section bearing the mouth; now often placed within the annelids.',

  // Candidate Phyla Radiation (CPR) & micro-lineages
  patescibacteria:    'A vast supergroup of nanobacteria with highly reduced genomes that depend on symbiotic host microbes to survive.',
  lindowbacteria:     'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  aureabacteria:      'Candidate bacteria (also called Auribacterota) known from environmental genomes, including from an Antarctic lake.',
  ratteibacteria:     'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  delongbacteria:     'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  omnitrophota:       'Uncultured microbes widespread across deep-ocean muds and deep global aquifers.',
  aerophobota:        'Uncultured anaerobic microbes found in deep-ocean muds and anoxic aquifer sediments.',
  zixibacteria:       'Uncultured microbes identified by environmental DNA in deep marine and aquifer sediments.',
  latescibacterota:   'Uncultured organisms widespread across deep-ocean muds and subsurface aquifers.',
  dependentiae:       'Bacteria (formerly TM6) named for their dependence on host organisms.',
  firestonebacteria:  'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  dormibacterota:     'Soil candidate bacteria adapted to metabolic dormancy during nutrient-limited conditions.',
  caldatribacteriota: 'Anaerobic bacteria of seabed sediments, dominant in deeper layers at some sites; some may be able to fix nitrogen.',
  hydrogenedentota:   'Uncultured candidate bacteria whose genomes suggest they can use cellulose derivatives, glycerol, fatty acids and phosphonates.',

  // Classical & specialised lineages
  chloroflexi:        'Green non-sulfur bacteria that use light for energy without producing oxygen.',
  chloroflexota:      'Green non-sulfur bacteria that use light for energy without producing oxygen.',
  thermotogota:       'Heat-loving bacteria wrapped in a distinctive outer sheath-like envelope resembling a toga.',
  nitrospinota:       'Marine bacteria that play a critical role in ocean nitrogen cycling.',
  thermosulfidibacterota: 'Heat-dwelling bacteria found near deep-sea volcanic vents that process sulfur compounds.',
  cyanobacteria:      'Photosynthetic bacteria (blue-green algae) responsible for creating Earth\'s oxygen atmosphere over billions of years.',
  cyanobacteriota:    'Photosynthetic bacteria (blue-green algae) responsible for creating Earth\'s oxygen atmosphere over billions of years.',
  chrysiogenota:      'Unusual bacteria that generate metabolic energy by reducing arsenic compounds.',
  synergistota:       'Gut microbes that break down complex amino acids and proteins in anaerobic digestive environments.',
  calditrichota:      'Deep-sea bacteria specialised for degrading complex organic matter on the ocean floor.',
  deinococcota:       'Extraordinary extremophiles famous for surviving radiation doses that would be lethal to almost any other organism.',
  coprothermobacterota:'Heat-loving microbes that ferment proteins and organic matter in manure and compost.',
  actinobacteriota:   'Soil bacteria responsible for producing the majority of natural antibiotics used in medicine.',
  actinomycetota:     'Soil bacteria responsible for producing the majority of natural antibiotics used in medicine.',
  gemmatimonadota:    'Dry-soil specialists with the rare ability to harvest solar light energy.',

  // Environmental & CPR candidate groups
  wallbacteria:       'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  riflebacteria:      'Candidate bacteria predicted to be anaerobes that grow by fermentation or by reducing iron.',
  elusimicrobiota:    'Tiny cells found inside animal intestines, named for being elusive to culture in the lab.',
  calescibacterota:   'Uncultured bacteria living in geothermal hot spring environments.',
  fermentibacterota:  'Specialised anaerobic microbes that ferment organic compounds in low-oxygen environments.',
  eremiobacterota:    'Uncultured soil and moss-associated bacteria; proposed lifestyles include capturing light energy without producing oxygen.',
  muirbacteria:       'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  krumholzibacteriota: 'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  armatimonadota:     'Widespread environmental bacteria frequently found in thermal and geothermal areas.',
  tectomicrobia:      'Bacteria often found in marine sponges, including Entotheonella, a source of many bioactive compounds.',
  schekmanbacteria:   'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  bipolaricaulota:    'Mostly uncultured bacteria (formerly OP1 or Acetothermia) of hot and subsurface habitats, some able to make acetate.',
  goldbacteria:       'A candidate phylum from the rare biosphere, whose genomes encode unusual cellulases.',
  mcinerneyibacteriota:'Uncultured bacteria predicted to feed on amino acids (Mcinerneyibacterium aminivorans).',
  desantisbacteria:   'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  atribacterota:      'Anaerobic bacteria common in methane-rich sediments, and sometimes abundant in marine sediments, geothermal springs and oil deposits.',
  eisenbacteria:      'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  margulisbacteria:   'Microbes phylogenetically close to the cyanobacteria, found in sediments, groundwater, seawater and insect guts.',
  marinisomatota:     'Uncultured marine bacteria (SAR406), some carrying many genes for breaking down complex carbohydrates.',
  moduliflexota:      'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  edwardsbacteria:    'A candidate bacterial lineage known almost entirely from environmental genomes; little is known of its biology.',
  sumerlaeota:        'A rarely reported lineage found worldwide, especially in cold desert soils and deep-sea sediments.',

  // ── Protists — Alveolates ─────────────────────────────────────────────────
  myzozoa:            'A massive alveolate group containing dinoflagellates (bioluminescence, red tides) and apicomplexans (obligate parasites including the malaria-causing Plasmodium).',
  ciliophora:         'Complex single-celled organisms densely covered in hair-like cilia used for rapid swimming and feeding — includes the famous Paramecium.',
  acavomonidia:       'A newly discovered predatory, bi-flagellated marine lineage — a crucial deep-branching "missing link" at the base of all alveolates.',

  // ── Protists — Stramenopiles ──────────────────────────────────────────────
  xanthophyceae:      'Yellow-green algae — photosynthetic freshwater and terrestrial algae often forming delicate, branching thread-like filaments.',
  bigyra:             'Primarily heterotrophic stramenopiles, including bicosoecid flagellates, gut-dwelling opalinids and slime nets.',
  oomycota:           'Water moulds and downy mildews — evolutionarily closer to kelp than true fungi, including Phytophthora infestans (cause of the Great Irish Potato Famine).',

  // ── Protists — Rhizaria & marine protists ─────────────────────────────────
  foraminifera:       'Amoeboid protists that build intricate calcium carbonate shells whose fossil accumulations form the world\'s chalk and limestone deposits.',
  cercozoa:           'A highly diverse phylum of single-celled amoebae and flagellates, including natural predators of many bacteria.',
  heliozoa:           'Spherical amoeboids ("sun-animalcules") that project rigid, needle-like axopodia outward in all directions to impale floating prey.',

  // ── Protists — Specialised algal micro-lineages ───────────────────────────
  haptophyta:         'Primarily marine phytoplankton capable of massive oceanic blooms, notable for secreting intricate calcium plates called coccoliths.',
  prymnesiophyta:     'Primarily marine phytoplankton capable of massive oceanic blooms, notable for secreting intricate calcium plates called coccoliths.',
  picozoa:            'Exceptionally tiny heterotrophic marine protists (picoplanktonic) that feed almost exclusively on dissolved organic particles.',
  cryptophyta:        'Small, flagellated algae that acquired their chloroplasts via an ancient secondary endosymbiosis with a red alga.',
  cryptomonada:       'Small, flagellated algae that acquired their chloroplasts via an ancient secondary endosymbiosis with a red alga.',

  // ── Fungi — Higher fungi (Dikarya) ────────────────────────────────────────
  basidiomycota:      'Club fungi — includes mushrooms, puffballs, bracket fungi, and crop parasites like rusts and smuts; releases sexual spores from club-shaped basidia.',
  ascomycota:         'Sac fungi — the largest fungal phylum, containing yeasts, truffles, morels, and penicillin-producing moulds; spores form inside sac-like asci.',

  // ── Fungi — Early-diverging basal clades ─────────────────────────────────
  mucoromycota:       'Includes common saprotrophic moulds like black bread mould (Rhizopus stolonifer) and many beneficial plant-associated fungi.',
  zoopagomycota:      'Specialised parasites and predators of microscopic soil animals — captures and consumes amoebae, nematodes, and rotifers.',
  entomophthoromycota:'Aggressive insect-killing fungi famous for hijacking arthropod behaviour ("zombie flies") before erupting outward to disperse spores.',
  sanchytriomycota:   'A recently discovered zoosporic phylum of single-celled fungi that parasitise freshwater algae; spores move in an unusual amoeboid fashion.',
  neocallimastigomycota:'Anaerobic, flagellated fungi living exclusively in herbivore digestive tracts, essential for fermenting plant cellulose in cattle, sheep, and elephants.',
  chytridiomycota:    'Primitive aquatic fungi (chytrids) with flagellated swimming spores; includes the pathogen driving global amphibian population declines.',
  chytridiomycetes:   'Primitive aquatic fungi (chytrids) with flagellated swimming spores; includes the pathogen driving global amphibian population declines.',
  glomeromycota:      'Essential soil fungi forming arbuscular mycorrhizae with roughly 80% of all land plant species, trading captured minerals for plant sugars.',
  blastocladiomycota: 'Zoosporic water and soil fungi exhibiting a true alternation of generations between distinct haploid and diploid individuals.',
  zygomycota:         'A former catchall phylum now split by genomic sequencing into Mucoromycota and Zoopagomycota.',

  // ── Protozoa ──────────────────────────────────────────────────────────────
  // Classical & well-known groups
  amoebozoa:          'Organisms that lack a fixed body shape and move or capture prey by dynamically extending fluid cytoplasmic extensions called pseudopods ("false feet").',
  euglenozoa:         'A large group of flagellates, including photosynthetic euglenids and parasitic kinetoplastids such as trypanosomes.',
  mycetozoa:          'Amoeba-like cells that can socially aggregate into large multicellular sheets or "slugs" that migrate and build spore-bearing fruiting structures.',
  eumycetozoa:        'Amoeba-like cells that can socially aggregate into large multicellular sheets or "slugs" that migrate and build spore-bearing fruiting structures.',
  dictyostelia:       'Social amoebae that aggregate under starvation into a motile multicellular slug that forms a fruiting body to disperse spores.',
  sarcomastigophora:  'A broad historical grouping that formerly united all amoebas and flagellated protozoans based on their shared locomotion mechanisms.',

  // Evolutionary links to other kingdoms
  choanozoa:          'Single-celled protists related to animals and fungi, notably the collared choanoflagellates — the closest living relatives of animals.',
  choanoflagellatea:  'Single-celled marine flagellates with a characteristic collar of microvilli — the closest living unicellular relatives of all animals.',
  microsporidia:      'Highly specialised, spore-forming intracellular parasites — historically classed as protozoans but genomically proven to be highly reduced, degenerate fungi.',
  microspora:         'Highly specialised, spore-forming intracellular parasites — historically classed as protozoans but genomically proven to be highly reduced, degenerate fungi.',

  // Specialised and deep-branching flagellates
  metamonada:         'A large group of anaerobic flagellates that entirely lack conventional mitochondria, including the notorious intestinal parasite Giardia.',
  loukozoa:           'Free-living flagellated protists with a distinct deep ventral feeding groove used to scoop up environmental bacteria.',
  sulcozoa:           'A proposed protozoan grouping of flagellates with a ventral groove, including apusomonads and breviates, later found to be deeply paraphyletic.',

  // Microfossils
  calcitarcha:        'An enigmatic phylum of spherical, calcium-walled microfossils of uncertain origin found in ancient rocks — likely fossilised prehistoric microbial cysts.',

  // ── Viruses — Archaeal & extremophile viruses ─────────────────────────────
  ampullaviridae:     'Bottle-shaped enveloped viruses that exclusively infect hyperthermophilic archaea in hot springs.',
  bicaudaviridae:     'Lemon-shaped viruses that uniquely grow long wire-like tails after being released from their host cell.',
  clavaviridae:       'Highly rigid, rod-shaped viruses with a distinctive helical structural layout infecting archaea.',
  fuselloviridae:     'Spindle- or lemon-shaped viruses that exit host cells by budding without lysing (destroying) them.',
  globuloviridae:     'Spherical, enveloped archaeal viruses harbouring double-stranded DNA genomes.',
  guttaviridae:       'Droplet-shaped archaeal viruses covered in structural surface fibres concentrated at one end.',
  plasmaviridae:      'Enveloped, pleomorphic (shape-shifting) viruses that infect Mollicutes, bacteria with no cell wall.',
  portogloboviridae:  'Spherical archaeal viruses with double-stranded DNA genomes, whose capsid proteins may shed light on the origin of other DNA viruses.',
  spiraviridae:       'Coil-shaped, non-enveloped archaeal viruses that resemble a tightly wound spring.',

  // ── Viruses — Plant & agricultural viruses / viroids ─────────────────────
  avsunviroidae:      'Small, circular naked RNA molecules (viroids) with no protein coat that replicate exclusively inside plant chloroplasts.',
  comoviridae:        'Plant viruses often transmitted by beetles, causing mosaic and mottling symptoms in crops.',
  flexiviridae:       'Filamentous, highly flexible plant viruses responsible for widespread agricultural crop damage.',
  luteoviridae:       'Plant viruses restricted to vascular phloem tissue and transmitted specifically by aphids.',
  ophioviridae:       'Highly kinked, snake-like filamentous plant viruses with a fragmented RNA genome.',
  pospiviroidae:      'Naked RNA pathogens (viroids) that replicate inside the host plant\'s nucleus, causing severe stunting diseases.',

  // ── Viruses — Vertebrate & insect viruses ────────────────────────────────
  anelloviridae:      'Small, non-enveloped viruses with circular single-stranded DNA, ubiquitous in human and mammal blood plasma.',
  bunyaviridae:       'A former family of enveloped, segmented RNA viruses, mostly transmitted by arthropods; hantaviruses are a notable exception.',
  papovaviridae:      'A former taxonomic family that combined papillomaviruses and polyomaviruses (both tumour-associated DNA viruses) before genomic reclassification.',
  polydnaviridae:     'Symbiotic viruses integrated into parasitic wasp genomes, injected into caterpillar hosts to suppress the host\'s immune defences.',

  // ── Viruses — Bacterial viruses (bacteriophages) ─────────────────────────
  leviviridae:        'Small, non-enveloped RNA bacteriophages that infect bacteria by attaching to their cellular pili appendages.',

  // ── Viruses — Sub-viral elements & non-viral agents ──────────────────────
  alphasatellitidae:  'DNA satellite molecules that cannot replicate independently — they hijack the replication machinery of co-infecting helper viruses.',
  tolecusatellitidae: 'DNA satellite molecules that cannot replicate independently — they hijack the replication machinery of co-infecting helper viruses.',
  satellites:         'Sub-viral particles (nucleic acids or viruses) entirely dependent on a companion helper virus to multiply.',
  prions:             'Not viruses — misfolded infectious proteins that contain no DNA or RNA, causing fatal neurodegenerative diseases like Mad Cow Disease (BSE).',

  // ── Viruses — Database structural placeholders ───────────────────────────
  styloviridae:       'An older name for a family of tailed bacteriophages, classified by the shape of their particles.',
};

// ── Tooltip ────────────────────────────────────────────────────────────────

let _tooltip = null;

function _ensureTooltip() {
  if (_tooltip) return _tooltip;
  _tooltip = document.createElement('div');
  Object.assign(_tooltip.style, {
    position:      'fixed',
    maxWidth:      '280px',
    background:    '#1f2937',
    color:         '#d1d5db',
    border:        '1px solid #374151',
    borderRadius:  '6px',
    padding:       '8px 10px',
    fontSize:      '12px',
    lineHeight:    '1.5',
    pointerEvents: 'none',
    zIndex:        '1000',
    display:       'none',
    boxShadow:     '0 4px 16px rgba(0,0,0,0.5)',
  });
  document.body.appendChild(_tooltip);
  return _tooltip;
}

// Placeholder nodes from the source, not taxa. Exact shapes only: "incertae" alone is
// also a real species epithet (Tamerlania incertae).
const _INCERTAE_SEDIS = /^incertae sedis$|_incertae_sedis$|^family-incertae$/i;
const _INCERTAE_SEDIS_DESCRIPTION =
  'Of uncertain placement: species accepted as real, but not yet assigned to a place at this level of the classification. Not a natural group.';

/** The hover description for a taxon by name; undefined if it has none. */
export function taxonDescription(name, rank) {
  if (_INCERTAE_SEDIS.test(name || '')) return _INCERTAE_SEDIS_DESCRIPTION;
  const key = (name || '').toLowerCase();
  if (rank === 'domain') return Object.hasOwn(_DOMAIN_DESCRIPTIONS, key) ? _DOMAIN_DESCRIPTIONS[key] : undefined;
  if (rank === 'order' && Object.hasOwn(ORDER_DESCRIPTIONS, key)) return ORDER_DESCRIPTIONS[key];
  if (rank === 'order' && Object.hasOwn(OTHER_ORDER_DESCRIPTIONS, key)) return OTHER_ORDER_DESCRIPTIONS[key];
  // A genus can share its name with a class (Branchiura, Appendicularia)
  if (rank === 'genus' || rank === 'species') return undefined;
  if (Object.hasOwn(_TAXON_DESCRIPTIONS, key)) return _TAXON_DESCRIPTIONS[key];
  if (Object.hasOwn(CLASS_DESCRIPTIONS, key)) return CLASS_DESCRIPTIONS[key];
  if (Object.hasOwn(UPPER_DESCRIPTIONS, key)) return UPPER_DESCRIPTIONS[key];
  return undefined;
}

// Ranks an automatic line names a node after, nearest first; and those that get no line.
const _MAIN_RANKS = new Set(['kingdom', 'phylum', 'class', 'order', 'family']);
const _NO_LINE = new Set(['genus', 'subgenus', 'species', 'subspecies', 'variety', 'form',
                          'more', 'hidden', 'root', '']);

function _ancestorLabel(data) {
  const common = data.common_names?.[0];
  const name = common && common.toLowerCase() !== data.name.toLowerCase()
    ? `${data.name} (${common})` : data.name;
  return _MAIN_RANKS.has(data.rank) || data.rank === 'domain' ? `the ${data.rank} ${name}` : name;
}

function _realParent(node) {
  let p = node.parent;
  while (p && (p.data.rank === 'alpha' || p.data.rank === 'unclassified')) p = p.parent;
  return p;
}

/**
 * The hover description for a tree node (a d3 hierarchy node): its written text,
 * else a line from its place in the tree ("A family in the order Coleoptera").
 * Undefined for genera and species, which open the species panel instead.
 */
export function nodeDescription(node) {
  const { name, rank } = node.data;
  const written = taxonDescription(name, rank);
  if (written) return written;
  if (_NO_LINE.has(rank || '')) return undefined;

  const parent = _realParent(node);
  if (!parent) return undefined;
  if (rank === 'alpha') {
    const letter = (name.match(/^\[(.)\]/) || [])[1];
    return `Members of ${parent.data.name} starting with ${letter}, grouped by letter because there are too many to show at once.`;
  }
  if (rank === 'unclassified') {
    return `Members of ${parent.data.name} that sit directly beneath it, without the level in between that the classification normally has.`;
  }

  let above = parent;
  while (above && !_MAIN_RANKS.has(above.data.rank)) above = _realParent(above);
  const word = rank === 'unranked' ? 'group' : rank.replace(/ (zoology|botany)$/, '');
  const article = /^[aeiou]/i.test(word) ? 'An' : 'A';
  return `${article} ${word} in ${_ancestorLabel((above || parent).data)}.`;
}

function _showTooltip(event, node) {
  const desc = nodeDescription(node);
  if (!desc) return;
  const tt = _ensureTooltip();
  tt.textContent = desc;
  tt.style.display = 'block';
  _placeTooltip(event, tt);
}

function _moveTooltip(event) {
  if (_tooltip && _tooltip.style.display !== 'none') _placeTooltip(event, _tooltip);
}

function _hideTooltip() {
  if (_tooltip) _tooltip.style.display = 'none';
}

function _placeTooltip(event, tt) {
  const pad = 14;
  let x = event.clientX + pad;
  let y = event.clientY - pad;
  tt.style.left = `${x}px`;
  tt.style.top  = `${y}px`;
  // Correct right/bottom overflow after the browser has laid it out
  const r = tt.getBoundingClientRect();
  if (r.right  > window.innerWidth  - 4) x = event.clientX - r.width  - pad;
  if (r.bottom > window.innerHeight - 4) y = event.clientY - r.height - pad;
  tt.style.left = `${x}px`;
  tt.style.top  = `${y}px`;
}

let _svg          = null;
let _inner        = null;
let _zoom         = null;
let _gLink        = null;
let _gNode        = null;
let _containerEl  = null;
let _zoomInited   = false;
let _selectedNodeId = null;
let _highlightPaths = [];
// Species and the ranks below it (COL uses botanical/zoological infraspecific ranks):
// sisters at these ranks stay lit beside a selected one
const _SPECIES_RANKS = new Set([
  'species', 'subspecies', 'variety', 'subvariety', 'form', 'subform', 'proles', 'natio',
  'aberration', 'lusus', 'mutatio', 'forma specialis', 'infraspecific name', 'infrasubspecific name',
]);
let _hideExtinct    = false;

const _tree    = d3.tree().nodeSize([DX, DY]);
let _rootData  = null;

// ── Public API ─────────────────────────────────────────────────────────────

export async function initTree(containerId) {
  _containerEl = document.getElementById(containerId);

  _svg = d3.select(`#${containerId}`)
    .append('svg')
    .attr('width', '100%')
    .attr('height', _containerEl.clientHeight || 650);

  _inner = _svg.append('g');

  // Ctrl+scroll → zoom; plain scroll → CSS scrollbar; drag → pan
  _zoom = d3.zoom()
    .scaleExtent([0.05, 4])
    .filter(evt => evt.type === 'wheel' ? evt.ctrlKey : !evt.button)
    .on('zoom', e => _inner.attr('transform', e.transform));

  _svg.call(_zoom);

  _gLink = _inner.append('g')
    .attr('fill', 'none')
    .attr('stroke', '#6b7280')
    .attr('stroke-width', 1.5);

  _gNode = _inner.append('g');

  const kingdoms = await loadNode('');
  _rootData = {
    node_id: '__root__',
    name: 'Life',
    rank: 'root',
    common_names: [],
    _loaded: true,
    children: kingdoms.map(_freshNode),
  };

  _render();
}

export async function loadNode(taxonPath) {
  let url;
  if (!taxonPath) {
    url = `${API}/api/taxonomy/root`;
  } else if (taxonPath.startsWith('__alpha__')) {
    const inner    = taxonPath.slice('__alpha__'.length);
    const lastPipe = inner.lastIndexOf('|');
    const parent   = inner.slice(0, lastPipe);
    const letter   = inner.slice(lastPipe + 1);
    if (parent.startsWith('__unclassified__')) {
      const actualPath = parent.slice('__unclassified__'.length);
      url = `${API}/api/taxonomy/unclassified?node_id=${encodeURIComponent(actualPath)}&letter=${encodeURIComponent(letter)}`;
    } else {
      url = `${API}/api/taxonomy/alpha?node_id=${encodeURIComponent(parent)}&letter=${encodeURIComponent(letter)}`;
    }
  } else if (taxonPath.startsWith('__unclassified__')) {
    const parentPath = taxonPath.slice('__unclassified__'.length);
    url = `${API}/api/taxonomy/unclassified?node_id=${encodeURIComponent(parentPath)}`;
  } else {
    url = `${API}/api/taxonomy/zoom?node_id=${encodeURIComponent(taxonPath)}&depth=1`;
  }
  try {
    const res = await fetch(url);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

/** Show or hide extinct taxa (the selected / searched path always stays visible). */
export function setHideExtinct(hide) {
  _hideExtinct = !!hide;
  if (_gNode) _render();
}

/**
 * Update a loaded node's extinct flag (e.g. learned by the species panel's GBIF
 * lookup after the branch loaded) and re-render if it changed. Unknown (null)
 * never clears a flag. Returns true when the tree changed.
 */
export function setNodeExtinct(taxonPath, extinct) {
  if (typeof extinct !== 'boolean' || !_rootData || !taxonPath) return false;
  const node = _findLoaded(taxonPath);
  if (!node || node.extinct === extinct) return false;
  node.extinct = extinct;
  if (_gNode) _render();
  return true;
}

/**
 * After a species is flagged extinct the backend may have flagged its genus,
 * family, ... too (all their species now extinct). Re-read loaded ancestors,
 * nearest first, until one is not extinct.
 */
export async function refreshAncestorFlags(taxonPath) {
  const segments = (taxonPath || '').split('|');
  for (let i = segments.length - 1; i >= 2; i--) {
    const path = segments.slice(0, i).join('|');
    if (!_findLoaded(path)) continue;
    let node;
    try {
      const res = await fetch(`${API}/api/taxonomy/node?node_id=${encodeURIComponent(path)}`);
      node = res.ok ? await res.json() : null;
    } catch {
      node = null;
    }
    if (node?.extinct !== true) return;
    setNodeExtinct(path, true);
  }
}

function _allKids(node) {
  return [...(node.children || []), ...(node._children || [])];
}

/**
 * Where a walk down `taxonPath` starts. Stored paths begin at the kingdom, with no
 * domain in them, so a path whose first segment sits under a domain starts there.
 */
function _walkStart(taxonPath) {
  const first = taxonPath.split('|')[0];
  return _allKids(_rootData).find(
    n => n.rank === 'domain' && _allKids(n).some(k => k.node_id === first),
  ) ?? _rootData;
}

function _findLoaded(taxonPath) {
  const segments = taxonPath.split('|');
  let current = _walkStart(taxonPath);
  for (let i = 0; i < segments.length && current; i++) {
    const partial = segments.slice(0, i + 1).join('|');
    const kids = _allKids(current);
    // alpha / unclassified buckets sit between a parent and its children
    current = kids.find(c => c.node_id === partial)
      ?? kids.filter(c => c.node_id.startsWith('__'))
             .flatMap(b => [...(b.children || []), ...(b._children || [])])
             .find(c => c.node_id === partial);
  }
  return current ?? null;
}

/** Replace the tree's root data and re-render. */
export function renderTree(data) {
  _rootData = data;
  _render();
}

export async function searchSpecies(query) {
  const q = (query || '').trim();
  if (q.length < 2) return [];
  const res = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}&limit=20`);
  if (!res.ok) return [];
  return res.json();
}

/**
 * Highlight nodes whose taxon_path is in `taxonPaths`, plus any visible
 * ancestor whose node_id is a prefix of a matched path.  Pass [] to clear.
 *
 * State is stored in `_highlightPaths` so that `_render()` can apply the same
 * opacity to newly-entering nodes — preventing D3's enter transition (0→1)
 * from overriding the dim value on non-path nodes.
 */
export function highlightNodes(taxonPaths) {
  _highlightPaths = (taxonPaths || []).filter(Boolean);
  if (!_gNode) return;
  _gNode.selectAll('g').attr('opacity', _highlightOpacity);
}

function _highlightOpacity(d) {
  if (!_highlightPaths.length) return 1;
  // One species opened (click, search, chat link): its sister species stay lit
  if (_highlightPaths.length === 1 && _SPECIES_RANKS.has(d.data.rank)
      && d.parent?.children?.some(c => c.data.node_id === _highlightPaths[0])) return 1;
  const ids = d.data.rank === 'domain' ? [d.data.node_id, ..._allKids(d.data).map(k => k.node_id)] : [d.data.node_id];
  for (const p of _highlightPaths) {
    if (ids.some(id => id === p || p.startsWith(id + '|'))) return 1;
  }
  return 0.12;
}

/**
 * Walk down the tree, expanding each ancestor of `taxonPath` so the target
 * species node becomes visible, then re-render.
 */
export async function expandToNode(taxonPath) {
  if (!_rootData || !taxonPath) return;
  const segments = taxonPath.split('|');

  document.dispatchEvent(new CustomEvent('tree-loading', { detail: { loading: true } }));
  let current = _walkStart(taxonPath);
  if (current._children && !current.children) {
    // A collapsed domain reopens whole, with all its kingdoms
    current.children  = current._children;
    current._children = null;
  }

  for (let i = 0; i < segments.length - 1; i++) {
    const partialPath    = segments.slice(0, i + 1).join('|');
    const isDirectParent = i === segments.length - 2;

    // Search visible children first, then collapsed children
    const allKids = [...(current.children || []), ...(current._children || [])];
    let target = allKids.find(c => c.node_id === partialPath);

    if (!target) {
      // Try alpha drilling before attempting a stale-refresh or injection
      target = await _drillAlpha(current, partialPath);
    }

    if (!target) {
      // Not in the tree yet — if parent was stale-loaded, re-fetch it first
      if (current._loaded && current.node_id !== '__root__') {
        const refreshed = await loadNode(current.node_id);
        if (refreshed.length > 0) {
          current.children  = refreshed.map(_freshNode);
          current._loaded   = true;
          current._pathOnly = false;
          current._children = null;
          target = current.children.find(c => c.node_id === partialPath);
          if (!target) {
            target = await _drillAlpha(current, partialPath);
          }
        }
      }
    }

    if (!target) {
      // Still not found — inject the ancestor node directly via /api/taxonomy/node
      const res = await fetch(
        `${API}/api/taxonomy/node?node_id=${encodeURIComponent(partialPath)}`,
      ).catch(() => null);
      if (!res?.ok) break;
      const nodeData = await res.json();
      if (nodeData?.node_id === partialPath) {
        // Exact match — normal injection
        target = _freshNode(nodeData);
        if (!current.children) current.children = [];
        current.children.push(target);
      } else if (nodeData?.node_id?.startsWith(partialPath + '|')) {
        // Response is a descendant of partialPath — the exact node may live
        // inside an alpha group.  Load current's children to detect alpha
        // sentinels, then drill into the matching bucket.
        if (current.node_id !== '__root__') {
          const loaded = await loadNode(current.node_id);
          if (loaded.length) {
            current.children  = loaded.map(_freshNode);
            current._loaded   = true;
            current._pathOnly = false;
            current._children = null;
          }
        }
        target = await _drillAlpha(current, partialPath);
        if (!target) break;
      } else {
        // Fallback: push whatever the endpoint returned (old behaviour)
        target = _freshNode(nodeData);
        if (!current.children) current.children = [];
        current.children.push(target);
      }
    } else if (current._children?.includes(target)) {
      // Move the target from collapsed back to visible children
      current._children = current._children.filter(c => c !== target);
      if (!current._children.length) current._children = null;
      if (!current.children) current.children = [];
      current.children.push(target);
    }

    // Prepare the target's children for the next descent step
    if (isDirectParent) {
      // Direct parent of the leaf: load (or reload) all children so the leaf appears
      // among its real siblings.
      if (!target._loaded || !(target.children || []).find(c => c.node_id === taxonPath)) {
        const childData  = await loadNode(partialPath);
        target._loaded   = true;
        target._pathOnly = false;
        if (childData.length > 0) {
          target.children = childData.map(_freshNode);
        }
      } else if (target._children && !target.children) {
        target.children  = target._children;
        target._children = null;
      }
    } else if (target._children && !target.children) {
      // Restore previously collapsed children
      target.children  = target._children;
      target._children = null;
    } else if (!target._loaded && !target.children) {
      // Not yet expanded: mark as a focused path node so siblings are not pre-loaded.
      // The next loop iteration injects the required child into this empty array.
      // Clicking the node later will trigger a full lazy-load of all siblings.
      target.children  = [];
      target._pathOnly = true;
    }

    current = target;
  }

  // Inject the target leaf if it is not already in the direct parent's children
  if (!(current.children || []).find(c => c.node_id === taxonPath)) {
    const res = await fetch(
      `${API}/api/taxonomy/node?node_id=${encodeURIComponent(taxonPath)}`,
    ).catch(() => null);
    if (res?.ok) {
      const injected = _freshNode(await res.json());
      if (current.children) current.children.push(injected);
      else current.children = [injected];
    }
  }

  _selectedNodeId = taxonPath;

  document.dispatchEvent(new CustomEvent('tree-loading', { detail: { loading: false } }));
  try { _render(); } catch (_) { /* jsdom lacks D3 transition timers */ }

  _panToNode(taxonPath);
}

/** Open a domain from search: domains have no species panel to show. */
export async function openDomain(nodeId) {
  const node = _rootData?.children?.find(n => n.node_id === nodeId && n.rank === 'domain');
  if (!node) return;
  if (node._children && !node.children) {
    node.children  = node._children;
    node._children = null;
  } else if (!node.children || node._pathOnly) {
    const kids = await loadNode(nodeId);
    node._loaded   = true;
    node._pathOnly = false;
    node.children  = kids.length ? kids.map(_freshNode) : null;
  }
  try { _render(); } catch (_) { /* jsdom lacks D3 transition timers */ }
  _panToNode(nodeId);
}

/** After the 280 ms D3 transition, pan the zoom to centre the node if it is out of view. */
function _panToNode(taxonPath) {
  if (_svg && _zoom && _gNode && _containerEl) {
    setTimeout(() => {
      const nodeEl = _gNode.selectAll('g')
        .filter(d => d.data.node_id === taxonPath)
        .node();
      if (!nodeEl) return;
      const cRect = _containerEl.getBoundingClientRect();
      const nRect = nodeEl.getBoundingClientRect();
      const inView = nRect.top    >= cRect.top    &&
                     nRect.bottom <= cRect.bottom  &&
                     nRect.left   >= cRect.left    &&
                     nRect.right  <= cRect.right;
      if (!inView) {
        const zt = d3.zoomTransform(_svg.node());
        const dx = cRect.left + cRect.width  / 2 - (nRect.left + nRect.width  / 2);
        const dy = cRect.top  + cRect.height / 2 - (nRect.top  + nRect.height / 2);
        _svg.transition().duration(300)
          .call(_zoom.transform, d3.zoomIdentity.translate(zt.x + dx, zt.y + dy).scale(zt.k));
      }
    }, 320);
  }
}

/** Return the display label for a node data object. */
export function nodeLabel(data) {
  const n = data.common_names;
  return n && n.length ? n[0] : data.name;
}

/** Tree label: "† " marks extinct taxa (fossils). */
export function treeLabel(data) {
  const label = data._pathOnly ? data.name : nodeLabel(data);
  return data.extinct === true ? `† ${label}` : label;
}

/**
 * Children to lay out for `data`. With `hide`, extinct children are dropped,
 * except those on a `keepPaths` path (selection / search), and a clickable
 * "† N extinct hidden" placeholder says how many went.
 */
export function visibleChildren(data, hide, keepPaths = []) {
  const kids = data.children;
  if (!hide || !kids) return kids;
  const keep = c => keepPaths.some(p => p && (p === c.node_id || p.startsWith(c.node_id + '|')));
  const shown = kids.filter(c => c.extinct !== true || keep(c));
  const hidden = kids.length - shown.length;
  if (!hidden) return kids;
  return [...shown, {
    node_id: `__hidden__${data.node_id}`,
    name: `† ${hidden.toLocaleString('en-US')} extinct hidden`,
    rank: 'hidden',
    common_names: [],
    _loaded: true,
    children: null,
  }];
}

/**
 * Walk the loaded tree from root to `taxonPath`, returning an array of
 * `{ node_id, label }` objects for each step (using common names where
 * available, scientific name otherwise).  Returns null if any ancestor is
 * not yet present in the loaded tree.
 */
export function getPathToNode(taxonPath) {
  if (!_rootData || !taxonPath) return null;
  const segments = taxonPath.split('|');
  const result = [];
  let current = _walkStart(taxonPath);
  if (current !== _rootData) result.push({ node_id: current.node_id, label: nodeLabel(current) });
  for (let i = 0; i < segments.length; i++) {
    const partialPath = segments.slice(0, i + 1).join('|');
    const allKids = [...(current.children || []), ...(current._children || [])];
    const next = allKids.find(c => c.node_id === partialPath);
    if (!next) return null;
    result.push({ node_id: partialPath, label: next._pathOnly ? next.name : nodeLabel(next) });
    current = next;
  }
  return result;
}

// ── Internal ───────────────────────────────────────────────────────────────

/**
 * If `current`'s loaded children are all alpha-group nodes, find the one
 * matching the first letter of the last segment of `partialPath`, load its
 * children, and return the child node whose node_id equals `partialPath`.
 * Returns null if current has no alpha children or no match is found.
 */
async function _drillAlpha(current, partialPath) {
  const allKids = [...(current.children || []), ...(current._children || [])];
  if (!allKids.length || !allKids.every(c => c.node_id.startsWith('__alpha__'))) return null;

  const lastSeg  = partialPath.split('|').pop();
  const ch       = lastSeg?.[0]?.toUpperCase() ?? '';
  const letter   = /^[A-Z]$/.test(ch) ? ch : '#';
  const alphaId  = `__alpha__${current.node_id}|${letter}`;
  let   alphaNode = allKids.find(c => c.node_id === alphaId);
  if (!alphaNode) return null;

  // Ensure alpha node is in visible (non-collapsed) children
  if (!current.children) current.children = [];
  if (!current.children.includes(alphaNode)) {
    current._children = (current._children || []).filter(c => c !== alphaNode);
    if (!current._children.length) current._children = null;
    current.children.push(alphaNode);
  }

  // Load alpha bucket on demand
  if (!alphaNode._loaded) {
    const loaded      = await loadNode(alphaNode.node_id);
    alphaNode._loaded = true;
    alphaNode.children = loaded.length ? loaded.map(_freshNode) : null;
  } else if (alphaNode._children && !alphaNode.children) {
    alphaNode.children  = alphaNode._children;
    alphaNode._children = null;
  }

  return (alphaNode.children || []).find(c => c.node_id === partialPath) ?? null;
}

function _freshNode(apiNode) {
  // Unclassified sentinel nodes arrive with children pre-populated from the API;
  // preserve them so the frontend doesn't try to lazy-load a synthetic node_id.
  const preloaded = Array.isArray(apiNode.children) && apiNode.children.length > 0;
  return {
    ...apiNode,
    _loaded: preloaded,
    children: preloaded ? apiNode.children.map(_freshNode) : null,
  };
}

function _render() {
  if (!_gLink || !_rootData) return;

  const keep = [_selectedNodeId, ..._highlightPaths];
  const root = d3.hierarchy(_rootData, d => visibleChildren(d, _hideExtinct, keep));
  _tree(root);

  // ── Compute layout extents ────────────────────────────────────────────────
  let minX = Infinity, maxX = -Infinity, maxY = -Infinity;
  root.each(d => {
    minX = Math.min(minX, d.x);
    maxX = Math.max(maxX, d.x);
    maxY = Math.max(maxY, d.y);
  });

  const containerH = _containerEl?.clientHeight || 650;
  const containerW = _containerEl?.clientWidth  || 1200;
  const svgNode    = _svg.node();

  // Current D3 zoom state (k = scale, x/y = translate)
  const zt    = svgNode ? d3.zoomTransform(svgNode) : d3.zoomIdentity;
  const scale = zt.k;
  let   tx    = zt.x;
  let   ty    = zt.y;

  if (!_zoomInited) {
    // ── First render: position root near the top-left ──────────────────────
    tx = 80;
    ty = PAD - minX * scale;
    _zoomInited = true;
    const initT = d3.zoomIdentity.scale(scale)
      .translate(tx / scale, ty / scale);
    try {
      _svg.call(_zoom.transform, initT);
    } catch (_) {
      _inner.attr('transform', `translate(${tx},${ty})`);
    }
  } else if (zt.y + minX * scale < PAD) {
    // ── Subsequent render: tree expanded upward beyond SVG top ─────────────
    // Shift the transform down so the new topmost node stays at y=PAD.
    ty = PAD - minX * scale;
    const adjT = d3.zoomIdentity.scale(scale)
      .translate(tx / scale, ty / scale);
    try {
      _svg.call(_zoom.transform, adjT);
    } catch (_) {
      _inner.attr('transform', `translate(${tx},${ty})`);
    }
  }

  // ── Resize SVG to contain all nodes (both axes) ───────────────────────────
  const LABEL_PAD = 320; // extra width so rightmost labels (incl. long subspecies) aren't clipped
  _svg
    .attr('width',  Math.max(tx + maxY * scale + LABEL_PAD, containerW))
    .attr('height', Math.max(ty + maxX * scale + PAD, containerH));

  const t = d3.transition().duration(280);

  // Links
  _gLink.selectAll('path')
    .data(root.links(), d => `${d.source.data.node_id}>${d.target.data.node_id}`)
    .join(
      enter  => enter.append('path').attr('opacity', 0)
        .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x))
        .call(s => s.transition(t).attr('opacity', 1)),
      // Opacity too: a re-render cancels any fade-in still running from the enter step
      update => update.call(s => s.transition(t)
        .attr('opacity', 1)
        .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x))),
      exit   => exit.call(s => s.transition(t).attr('opacity', 0).remove()),
    );

  // Nodes
  const isSentinel      = d => d.data.rank === 'more';
  const isUnclassified  = d => d.data.rank === 'unclassified';
  const isAlpha         = d => d.data.rank === 'alpha';
  const isHidden        = d => d.data.rank === 'hidden';
  const isMuted         = d => isSentinel(d) || isUnclassified(d) || isAlpha(d) || isHidden(d);

  _gNode.selectAll('g')
    .data(root.descendants(), d => d.data.node_id)
    .join(
      enter => {
        const g = enter.append('g')
          .attr('transform', d => `translate(${d.y},${d.x})`)
          .attr('opacity', 0)
          .attr('cursor', d => isSentinel(d) ? 'default' : 'pointer')
          .attr('data-rank', d => d.data.rank)
          .attr('data-node-id', d => d.data.node_id)
          .on('click',     (_, d)      => _onClick(d))
          .on('mouseover', (event, d)  => _showTooltip(event, d))
          .on('mousemove', (event)     => _moveTooltip(event))
          .on('mouseout',  ()          => _hideTooltip());

        g.append('circle')
          .attr('r', 5)
          .attr('stroke', '#111827')
          .attr('stroke-width', 1.5);


        g.append('text')
          .attr('dy', '0.31em')
          .attr('font-size', '11px');

        return g.call(s => s.transition(t).attr('opacity', _highlightOpacity));
      },
      update => update.call(s => s.transition(t)
        .attr('transform', d => `translate(${d.y},${d.x})`)
        .attr('opacity', _highlightOpacity)),
      exit => exit.call(s => s.transition(t).attr('opacity', 0).remove()),
    )
    .select('circle')
    .attr('r', d => d.data.node_id === _selectedNodeId ? 9 : 5)
    .attr('fill', d => isMuted(d) ? '#4b5563' : nodeDot(d.data, _selectedNodeId).fill)
    .attr('stroke', d => isMuted(d) ? DOT_CENTRE : nodeDot(d.data, _selectedNodeId).stroke)
    .attr('stroke-width', d => isMuted(d) ? 1.5 : nodeDot(d.data, _selectedNodeId).width);

  _gNode.selectAll('g').select('text')
    .attr('x', 8)
    .attr('text-anchor', 'start')
    // Outline in the page colour, so links leaving an expanded node don't cross its label
    .attr('stroke', '#030712')
    .attr('stroke-width', 3)
    .attr('paint-order', 'stroke')
    .attr('fill', d => (isMuted(d) || d.data.extinct === true) ? '#9ca3af' : '#e5e7eb')
    .attr('font-style', d => isMuted(d) ? 'italic' : 'normal')
    .text(d => treeLabel(d.data));
}

async function _onClick(d) {
  const data = d.data;
  if (data.rank === 'root' || data.rank === 'more') return;
  if (data.rank === 'hidden') {
    // Placeholder for filtered fossils: clicking it shows them again
    setHideExtinct(false);
    document.dispatchEvent(new CustomEvent('hide-extinct-changed', { detail: { hide: false } }));
    return;
  }

  if (data._pathOnly) {
    // Path-focused node from search navigation — user wants to see all siblings.
    // Reset to force a full lazy-load on the next step below.
    data._pathOnly = false;
    data.children  = null;
    data._children = null;
    data._loaded   = false;
  } else if (data.children && data.children.length > 0) {
    // Collapse
    data._children = data.children;
    data.children  = null;
    // The selected species is now out of sight: stop dimming the rest of the tree.
    // The species panel stays open (no species-selected event), so it can still be read.
    if (_selectedNodeId && String(_selectedNodeId).startsWith(data.node_id + '|')) {
      _selectedNodeId = null;
      highlightNodes([]);
    }
    _render();
    return;
  }

  if (data._children) {
    // Re-expand cached children
    data.children  = data._children;
    data._children = null;
    _render();
    return;
  }

  if (!data._loaded) {
    // First expansion (or forced reload after _pathOnly reset): lazy-load from API
    document.dispatchEvent(new CustomEvent('tree-loading', { detail: { loading: true } }));
    const childData = await loadNode(data.node_id);
    document.dispatchEvent(new CustomEvent('tree-loading', { detail: { loading: false } }));
    data._loaded = true;
    if (childData.length > 0) {
      data.children = childData.map(_freshNode);
      _render();
      return;
    }
    // No children → confirmed leaf: show detail panel (skip synthetic nodes)
    if (data.rank === 'unclassified' || data.rank === 'alpha' || data.rank === 'domain') return;
  }

  // Confirmed leaf: toggle selection and open detail panel
  const newId = _selectedNodeId === data.node_id ? null : data.node_id;
  _selectedNodeId = newId;
  highlightNodes(newId ? [newId] : []);
  _render();

  document.dispatchEvent(new CustomEvent('species-selected', {
    detail: { scientific_name: data.scientific_name || data.name, selected: newId !== null },
  }));
}

export function clearSelection() {
  _selectedNodeId = null;
  highlightNodes([]);
  if (_gNode) _render();
}
