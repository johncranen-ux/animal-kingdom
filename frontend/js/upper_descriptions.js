/**
 * Hover descriptions for the levels above class that visualizer.js does not cover:
 * kingdoms, virus realms, subkingdoms and infrakingdoms (phyla and the levels between
 * phylum and class to follow). Keys are lowercase scientific names. taxonDescription()
 * never shows these on a genus or species.
 *
 * Texts are in our own words from the group's Wikipedia summary; where that is thin,
 * they say only what the tree itself shows. Several Catalogue of Life nodes hold just the
 * members not placed lower down (Riboviria, Harosa, Bryobiotina); their texts say so.
 */
export const UPPER_DESCRIPTIONS = {
  // ── Eukaryote kingdoms ───────────────────────────────────────────────────
  animalia:     'Animals — many-celled organisms that feed on other living things or their remains, breathe oxygen, have muscle cells and, with few exceptions, can move. All descend from one common ancestor; insects make up most of the known species.',
  chromista:    'A proposed and debated kingdom of single-celled and many-celled organisms (e.g. diatoms, kelp, foraminifera, ciliates). Its photosynthetic members have plastids with chlorophyll c inside four membranes; the others are thought to have lost them.',
  fungi:        'Fungi — yeasts, moulds, mushrooms and the fungi of lichens. They take in food by absorbing it from their surroundings, not by photosynthesis or by eating.',
  plantae:      'Plants — organisms that make sugars from carbon dioxide and water using sunlight and the green pigment chlorophyll, or descend from ones that did; a few have become parasites. Includes flowering plants, conifers, ferns, mosses, and red and green algae.',
  protozoa:     'Protozoans — single-celled organisms with a nucleus that feed on other microbes or organic debris, free-living or parasitic (e.g. amoebas, euglenids, trypanosomes). A grouping of convenience, not one line of descent; once seen as "one-celled animals".',

  // ── Eukaryote subkingdoms and infrakingdoms ──────────────────────────────
  harosa:         'The SAR supergroup: stramenopiles (e.g. diatoms, kelp), alveolates (e.g. ciliates, dinoflagellates) and rhizarians (e.g. foraminifera). Here it holds families not yet placed in a lower group.',
  rhizaria:       'Mostly single-celled organisms such as foraminifera and radiolarians; few photosynthesise themselves, but many host algae. Here it holds members not yet placed in a phylum.',
  bryobiotina:    'The bryophytes: mosses, liverworts and hornworts. Here it holds what is not placed in one of their phyla, mostly fossil spores and fossil moss genera.',
  sarcomastigota: 'A subkingdom proposed for amoebas and many flagellates. Here it holds only a few poorly known genera not placed in a phylum.',
  eozoa:          'A subkingdom proposed for flagellates such as euglenids and trypanosomes. Here it holds only one family not placed in a phylum, the Bodonaceae.',

  // ── Bacterial kingdoms ───────────────────────────────────────────────────
  bacillati:      'About two-thirds of all prokaryote species: the gram-positive bacteria plus the cyanobacteria and their relatives. First named "Terrabacteria" for adaptations to life on land, such as resistance to environmental hazards and oxygen-producing photosynthesis.',
  pseudomonadati: 'About a third of all prokaryote species, mostly gram-negative bacteria (e.g. the proteobacteria, spirochaetes and Bacteroidota). First proposed under the name "Hydrobacteria".',
  thermotogati:   'Bacteria united by an outer, sheath-like membrane called the "toga"; includes the Thermotogota, Deinococcota and Synergistota.',
  fusobacteriati: 'Bacteria of a single phylum, the Fusobacteriota: rod-shaped, gram-negative bacteria that cannot live with oxygen and form no spores. Some live harmlessly in the body, others cause disease.',

  // ── Archaeal kingdoms ────────────────────────────────────────────────────
  methanobacteriati: 'A highly diverse kingdom of archaea: methane producers often found in guts, halobacteria that survive extreme salt, and some that live at very high temperatures.',
  nanobdellati:      'Nanoarchaea — "ultra-small" archaea, much smaller than others; many show signs of genes taken up from other domains of life. First proposed in 2013.',
  promethearchaeati: 'Asgard archaea — archaea that carry proteins otherwise typical of eukaryotes. Eukaryotes (animals, plants, fungi and their relatives) appear to have arisen from within this group.',
  thermoproteati:    'Archaea also known as "TACK", found from hot acid springs to cold waters, mostly living without oxygen and drawing energy from chemicals. Sister to the Asgard archaea, from which eukaryotes arose.',

  // ── Virus realms and kingdoms ────────────────────────────────────────────
  riboviria:      'The realm of viruses that copy their genome with an RNA-dependent polymerase: most RNA viruses plus the reverse-transcribing ones. Here it holds only the few members not placed in one of its kingdoms, Orthornavirae and Pararnavirae.',
  ribozyviria:    'Animal viruses whose small, single-stranded RNA genome cuts itself with built-in ribozymes; they borrow their envelope from a helper virus. Best known is hepatitis D virus, which depends on hepatitis B.',
  orthornavirae:  'RNA viruses that carry the gene for their own RNA-copying enzyme (e.g. coronaviruses, influenza and measles viruses). They mutate and recombine often, so they evolve quickly.',
  pararnavirae:   'Viruses that copy their genome through a reverse transcriptase, which makes DNA from RNA (e.g. retroviruses such as HIV, and hepatitis B virus). It holds a single phylum, Artverviricota.',
  bamfordvirae:   'DNA viruses whose main capsid protein has a "double jelly roll" fold (e.g. adenoviruses, poxviruses and the giant viruses). Named after Dennis Bamford, who first argued that these viruses share one origin.',
  heunggongvirae: 'Double-stranded DNA viruses built around the HK97-fold capsid protein: the tailed bacteriophages and the herpesviruses. Their DNA is packed into the capsid through a portal by a motor enzyme.',
  helvetiavirae:  'Viruses whose capsid proteins have a single "jelly roll" fold standing upright in the capsid wall. It holds a single phylum, Dividoviricota.',
  loebvirae:      'Bacteriophages with circular single-stranded DNA and long filamentous or rod-shaped particles, assembled as they are pushed out through the host cell\'s membrane.',
  sangervirae:    'Microviruses — very small bacteriophages with circular single-stranded DNA (e.g. phiX174, whose genome was the first DNA genome sequenced).',
  shotokuvirae:   'Viruses of eukaryotes sharing one kind of replication protein, mostly with small circular single-stranded DNA ("CRESS-DNA viruses", e.g. circoviruses, geminiviruses); also papillomaviruses and polyomaviruses.',
  trapavirae:     'Viruses of archaea without a fixed shape: an envelope with surface spikes around the DNA genome, and a distinctive V-shaped membrane-fusion protein.',
  zilligvirae:    'Viruses of archaea, many from hot geothermal springs, with long filamentous particles and double-stranded DNA held in the A-form.',
  abadenavirae:   'A kingdom of viruses that holds a single phylum, Produgelaviricota.',

  // ── Animal subphyla and infraphyla ───────────────────────────────────────
  // Most living arthropods and vertebrates sit in classes directly under their phylum;
  // these nodes then hold only what is not placed in a class, mostly fossils.
  artiopoda:       'Extinct arthropods: the trilobites and their close relatives. Here it holds fossil genera not placed in a class.',
  chelicerata:     'Arthropods with pincer- or fang-like mouthparts (chelicerae): arachnids, horseshoe crabs, sea spiders and extinct sea scorpions. Here it holds fossil groups not placed in a class.',
  crustacea:       'Crustaceans — mostly aquatic arthropods such as crabs, shrimp, krill, barnacles and copepods. Here it holds members not placed in a class, many of them fossils.',
  myriapoda:       'Myriapods — land-living arthropods with many legs, such as millipedes and centipedes. Here it holds three fossil genera not placed in a class.',
  linguliformea:   'Inarticulate brachiopods, the earliest brachiopods, from the Cambrian to today; most of their families died out long ago. Here it holds one fossil genus not placed in a class.',
  cephalochordata: 'Lancelets — small, fish-like, filter-feeding chordates that live in sea-floor sand. Here it holds early fossil chordates such as Pikaia, not placed in a class.',
  gnathostomata:   'Jawed vertebrates: nearly all living vertebrates, from sharks and bony fishes to mammals. Here it holds one fossil genus not placed in a class.',
  vertebrata:      'Vertebrates — animals with a backbone around the spinal cord and a skull around the brain. Here it holds those not placed in a class, almost all of them fossils.',
  catenulida:      'Small, free-living flatworms of fresh water and the sea, often forming chains of individuals as they bud.',
  rhabditophora:   'Most flatworms: all the parasitic ones (tapeworms, flukes) and most free-living ones, such as planarians and polyclads.',
  xenoturbellida:  'Very simple, worm-like animals of the sea floor, up to about 20 cm long; how they relate to other animals is unclear.',

  // ── Archaeal and bacterial phyla ─────────────────────────────────────────
  microcaldota:            'Ultra-small archaea known from a single species, Microcaldus variisymbioticus, named for its ability to live symbiotically with other microbes.',
  minisyncoccota:          'A phylum of bacteria with one valid class, Minisyncoccia.',
  mycoplasmatota:          'Bacteria without a cell wall and with very small genomes, many of them parasites (e.g. Mycoplasma, Ureaplasma, Spiroplasma, the phytoplasmas of plants).',
  abditibacteriota:        'Bacteria found in extreme places, from polar and desert soils to wastewater and mining sites; the first was grown from Antarctic soil.',
  balneolota:              'A small phylum of bacteria with a single class, Balneolia.',
  caldifarciminota:        'Bacteria first known only from DNA collected from the environment (as candidate phylum WOR-3); close relatives of the Cloacimonadota.',
  chlorobiota:             'Green sulfur bacteria — bacteria that photosynthesise without oxygen, using sulfur compounds.',
  kiritimatiellota:        'Gram-negative bacteria of guts and oxygen-poor waters, where they break down sugars such as sulfated polysaccharides.',
  lentisphaerota:          'A small phylum of bacteria, close relatives of the Chlamydiota and Verrucomicrobiota.',
  rhodothermota:           'A small phylum of bacteria with a single class, Rhodothermia.',
  thermodesulfobacteriota: 'Gram-negative bacteria that live without oxygen; many draw energy by reducing sulfate, others use other sulfur compounds or iron.',
  thermomicrobiota:        'Heat-loving bacteria, among the "green non-sulfur bacteria", with a single class, Thermomicrobia.',

  // ── Chromist phyla and subphyla ──────────────────────────────────────────
  chromeridophyta:    'Chrompodellids — single-celled alveolates: colpodellids, which prey on other microbes, and chromerids, photosynthetic algae living with corals. Close relatives of the apicomplexan parasites.',
  intramacronucleata: 'Most ciliates: those whose large nucleus divides with the help of microtubules inside it. Here it holds members not placed in a class.',
  miozoa:             'Alveolates that feed, or once fed, by sucking out the contents of prey cells: the dinoflagellates and the apicomplexan parasites, such as the malaria parasite Plasmodium.',
  apicomplexa:        'Mostly parasitic single-celled organisms with an apical complex for entering host cells (e.g. Plasmodium, Toxoplasma). Here it holds only what is not placed in a class.',
  dinoflagellata:     'Dinoflagellates — single-celled organisms, mostly marine plankton, with two flagella. Here it holds a few orders not placed in a class.',
  radiozoa:           'Radiolarians — single-celled marine plankton, under a fifth of a millimetre across, that build intricate mineral skeletons; they leave a rich fossil record.',

  // ── Fungal phyla ─────────────────────────────────────────────────────────
  entorrhizomycota: 'Fungi that parasitise plant roots and form galls on them, mainly on rushes and sedges; a small group related to the mushroom and sac fungi.',
  rozellomycota:    'Microbes that are either fungi or the nearest relatives of fungi, lacking a chitin cell wall when feeding; most live as parasites inside other cells. Here they include the microsporidia.',

  // ── Plant phyla and subphyla ─────────────────────────────────────────────
  prasinophytina:      'Green algae traditionally called prasinophytes, mostly tiny marine flagellates. Here it holds fossil genera not placed in a class.',
  prasinodermatophyta: 'A small group of marine green algae, sister to both the other green algae and the line that led to land plants.',
  rhodelphidia:        'Single-celled, flagellated predators in water, the closest known relatives of red algae; they keep a reduced plastid that no longer photosynthesises.',

  // ── Protozoan phyla and subphyla ─────────────────────────────────────────
  paramycia:        'A subphylum of choanozoans near the fungi. Here it holds one family, the Rozellidae, not placed in a class.',
  euglenoida:       'Euglenids — single-celled flagellates, common in fresh water, some green and photosynthetic, others feeding on particles. Here it holds one fossil genus not placed in a class.',
  hemimastigophora: 'Single-celled predators with two rows of flagella, first described in 1988; their DNA suggests an ancient line separate from all other eukaryote kingdoms.',
  nebulidia:        'Nebulids — single-celled predators of other microbes, in the recently described supergroup Provora.',
  nibbleridia:      'Nibblerids — single-celled predators that nibble at other microbes, in the recently described supergroup Provora.',
  percolozoa:       'Amoeboflagellates that can switch between amoeba and flagellate forms, including Naegleria fowleri, the cause of the often fatal amoebic meningitis.',

  // ── Virus phyla ──────────────────────────────────────────────────────────
  produgelaviricota:  'A phylum of DNA viruses, with two classes, Belvinaviricetes and Ainoaviricetes.',
  nucleocytoviricota: 'Large DNA viruses of eukaryotes (nucleocytoplasmic large DNA viruses): the giant viruses, poxviruses, African swine fever virus and relatives.',
  preplasmiviricota:  'DNA viruses with "double jelly roll" capsid proteins, including adenoviruses, virophages and the tectiviruses of bacteria; the name means "precursors of certain plasmids".',
  dividoviricota:     'Viruses with an inner membrane that infect salt-loving archaea, in a single class, Laserviricetes.',
  peploviricota:      'Herpesviruses — enveloped DNA viruses of animals, causing cold sores, chickenpox and shingles in humans.',
  uroviricota:        'Tailed bacteriophages — double-stranded DNA viruses with a head and a tail that infect bacteria and archaea; the most species-rich virus group in the tree.',
  hofneiviricota:     'Filamentous bacteriophages with circular single-stranded DNA, which leave their host by being pushed out through its membrane.',
  ambiviricota:       'RNA viruses of fungi whose genome codes for proteins in both directions (ambisense), so one strand carries two genes facing opposite ways.',
  artimaviricota:     'RNA viruses of heat- and acid-loving bacteria, known from a single species, Atsuirnavirus caloris.',
  duplornaviricota:   'Double-stranded RNA viruses (all but those in Pisuviricota), e.g. rotaviruses; their capsid is built from 60 pairs of capsid proteins.',
  kitrinoviricota:    'Positive-strand RNA viruses of eukaryotes not in Pisuviricota or Lenarviricota, e.g. flaviviruses (dengue, yellow fever), togaviruses and many plant viruses.',
  lenarviricota:      'Positive-strand RNA viruses of bacteria, plus some of eukaryotes such as mitoviruses; most have no capsid.',
  negarnaviricota:    'Negative-strand RNA viruses, whose genome is the mirror copy of their messenger RNA, e.g. influenza, measles, rabies and Ebola viruses.',
  pisuviricota:       'Positive-strand and some double-stranded RNA viruses of eukaryotes, e.g. picornaviruses (polio, common cold), coronaviruses and potyviruses.',
  artverviricota:     'All viruses that use a reverse transcriptase, which copies RNA into DNA (e.g. retroviruses such as HIV, and hepatitis B virus).',
  phixviricota:       'Microviruses — very small bacteriophages with circular single-stranded DNA, such as phiX174.',
  commensaviricota:   'Anelloviruses — small viruses with circular single-stranded DNA, found in vertebrates without causing known disease.',
  cossaviricota:      'Small DNA viruses of animals: parvoviruses, papillomaviruses and polyomaviruses. Named after Yvonne Cossart, who discovered parvovirus B19.',
  cressdnaviricota:   'CRESS-DNA viruses — eukaryote viruses with small circular single-stranded DNA, copied by rolling-circle replication (e.g. circoviruses, geminiviruses of plants).',
  calorviricota:      'Archaeal viruses without a fixed shape, in a single class, Caminiviricetes.',
  saleviricota:       'Archaeal viruses without a fixed shape that infect salt-loving archaea, in a single class, Huolimaviricetes.',
  taleaviricota:      'Viruses of archaea with long filamentous particles and double-stranded DNA held in the A-form, in a single class, Tokiviricetes.',
  // ── Levels between class and order (subclass, superorder, infraclass …) ──
  // Many hold only members not placed in an order; "fossils" is said only where the
  // DB marks most of them extinct.
  // Annelids
  oligochaeta:        'Oligochaetes — earthworms and their freshwater relatives. Here it holds a few genera not placed in an order.',
  canalipalpata:      'Polychaete worms with grooved feeding palps, many living in tubes (e.g. fan worms, spionids, terebellids, tubeworms).',
  echiura:            'Spoon worms — unsegmented marine worms with a spoon-shaped proboscis, once a phylum of their own, now counted as annelids. Here it holds genera not placed lower.',
  scolecida:          'Polychaete worms with few head appendages, mostly burrowers that eat sediment for its organic matter (e.g. bamboo worms, capitellids, lugworm relatives).',
  // Arthropods
  gymnoplea:          'Copepods that include the calanoids, the free-swimming plankton copepods. Here it holds two families not placed in an order.',
  podoplea:           'A large superorder of copepods, free-living and parasitic, found in all oceans as well as fresh water.',
  chilognatha:        'Most living millipedes. Here it holds families and genera not placed in an order.',
  colobognatha:       'Millipedes with reduced, often sucking mouthparts. Here it holds one genus not placed in an order.',
  helminthomorpha:    'Worm-like millipedes, the bulk of the class. Here it holds groups not placed in an order, mostly fossils.',
  juliformia:         'Cylindrical millipedes (e.g. Julida, Spirobolida, Spirostreptida). Here it holds members not placed in an order.',
  merocheta:          'Flat-backed millipedes (Polydesmida and relatives). Here it holds genera not placed in a family.',
  nematophora:        'Millipedes that spin silk from glands at the tail end. Here it holds members not placed in an order.',
  oniscomorpha:       'Pill millipedes, which roll into a ball like woodlice. Here it holds one family not placed in an order.',
  archaeorthoptera:   'Extinct insects of the Palaeozoic related to grasshoppers and crickets, all fossils.',
  afreminae:          'A beetle subfamily not placed in a family, with one genus, Afremus.',
  meligethiellinae:   'A beetle subfamily not placed in a family, with one fossil genus, Meligethiella.',
  palaeotylinae:      'A beetle subfamily not placed in a family, with one fossil genus, Palaeotylus.',
  podocopa:           'The larger of the two ostracod subclasses, told apart by a long inner branch of the second antenna. Here it holds members not placed in an order, mostly fossils.',
  cirripedia:         'Barnacles — marine crustaceans that cement themselves head-down and kick food in with their legs. Here it holds one family not placed in an order.',
  facetotecta:        'Crustaceans known only from their larvae ("y-larvae"); the adults have never been found.',
  rhizocephala:       'Parasitic barnacles that grow like roots through crabs and other crustaceans and castrate them.',
  trilobitomorpha:    'Trilobites and trilobite-like extinct arthropods. Here it holds groups not placed in a class, all fossils.',
  vicissicaudata:     'Extinct arthropods related to trilobites, such as the aglaspidids and Sidneyia; all fossils.',
  // Vertebrates
  actinistia:         'Coelacanths — lobe-finned fishes, closer to lungfishes and land vertebrates than to ray-finned fishes; one living genus, Latimeria, the rest fossils.',
  dinosauria:         'Dinosaurs — reptiles that dominated life on land through much of the Mesozoic. Here it holds the saurischians, almost all fossils; birds sit in their own class.',
  dipnoi:             'Lungfishes — freshwater fishes able to breathe air, close relatives of land vertebrates; many of the species here are fossils.',
  eutheria:           'Placental mammals and their extinct relatives. Here it holds the groups not placed in an order, almost all of them fossils.',
  metatheria:         'Marsupials and their extinct relatives. Here it holds groups not placed in an order, all fossils (e.g. the South American borhyaenids).',
  prototheria:        'Egg-laying mammals (monotremes) and early groups once linked with them. Here it holds fossil groups not placed in an order.',
  theria:             'Mammals that bear live young: placentals and marsupials. Here it holds early relatives not placed in an order, almost all fossils.',
  // Cnidarians and echinoderms
  hydroidolina:       'Most hydrozoans: hydroids, siphonophores and their medusae. Here it holds members not placed in an order, mostly fossils.',
  trachylinae:        'Hydrozoans whose medusae develop directly, without a hydroid stage. Here it holds one fossil genus.',
  ambuloasteroidea:   'Sea stars in the broad sense, living and fossil. Here it holds one fossil family not placed in an order.',
  forcipulatacea:     'Sea stars with tiny pincers (pedicellariae) on their skin, e.g. the common starfish Asterias.',
  plumasteridae:      'A fossil sea star family not placed in an order (Plumaster).',
  valvatacea:         'A superorder of sea stars, e.g. cushion stars, sun stars and the crown-of-thorns starfish.',
  articulata:         'All living sea lilies and feather stars and their fossil relatives. Here it holds one fossil family not placed in an order.',
  atelostomata:       'Irregular sea urchins without a jaw apparatus, such as heart urchins. Here it holds members not placed in an order, all fossils.',
  carinacea:          'Most living regular sea urchins, with fossils back to the Triassic. Here it holds members not placed in an order, all fossils.',
  echinacea:          'A superorder of regular sea urchins. Here it holds members not placed in an order, mostly fossils.',
  irregularia:        'Irregular sea urchins — sand dollars, heart urchins and relatives, from the Early Jurassic on. Here it holds members not placed in an order, almost all fossils.',
  luminacea:          'A group of sea urchins. Here it holds one fossil genus, Runa.',
  neognathostomata:   'Irregular sea urchins, including the sand dollars and cassiduloids. Here it holds members not placed in an order, mostly fossils.',
  metophiurida:       'Most brittle stars. Here it holds one fossil genus not placed in an order.',
  ophintegrida:       'One of the two superorders of brittle stars. Here it holds one fossil genus not placed in an order.',
  // Hemichordates
  cephalodiscida:     'Small, worm-shaped animals living in colonies in tubes they build on the sea floor, filter-feeding with tentacled arms.',
  graptolithina:      'Graptolites — colonial filter-feeders known mainly as fossils from the Cambrian to the Carboniferous, used to date rocks. Here it holds genera not placed in an order.',
  // Molluscs
  anomalodesmata:     'Marine clams, often with thin, pearly shells, including the predatory septibranchs. Here it holds fossil genera not placed lower.',
  archiheterodonta:   'Clams of the astartids, crassatellids and relatives. Here it holds genera not placed in a family, almost all fossils.',
  euheterodonta:      'Most heterodont clams (cockles, venus clams, razor clams). Here it holds fossil groups not placed in an order.',
  heteroconchia:      'A large group of clams with differentiated hinge teeth. Here it holds one fossil family not placed lower.',
  imparidentia:       'A major group of clams (e.g. venus clams, cockles, soft-shell clams, zebra mussels). Here it holds members not placed in an order, many of them fossils.',
  palaeoheterodonta:  'Clams with equal valves and hinge teeth in a single row: freshwater mussels and trigonias. Here it holds fossil families not placed in an order.',
  pteriomorphia:      'Marine clams such as oysters, scallops, mussels and ark clams. Here it holds fossil families not placed in an order.',
  coleoidea:          'Squids, octopuses, cuttlefish and the extinct belemnites — cephalopods with an internal shell or none. Here it holds members not placed in an order, almost all fossils.',
  decapodiformes:     'Ten-limbed cephalopods: squids and cuttlefish. Here it holds fossil groups not placed in an order.',
  multiceratoidea:    'A major group of Palaeozoic nautiloid cephalopods, all fossils. Here it holds families not placed in an order.',
  nautiloidea:        'Nautiloids — shelled cephalopods, today only Nautilus and Allonautilus. Here it holds fossil genera not placed in an order.',
  orthoceratoidea:    'Nautiloid cephalopods with mostly straight shells, all extinct. Here it holds fossils not placed in an order.',
  caenogastropoda:    'Most sea snails, plus some freshwater and land snails. Here it holds members not placed in an order, all fossils.',
  cerithiimorpha:     'Horn snails and their relatives, a now-abandoned grouping of marine snails. Here it holds members not placed in an order, all fossils.',
  eupulmonata:        'Air-breathing snails and slugs, mostly on land, some in salt marshes and mangroves. Here it holds members not placed in an order.',
  euthyneura:         'A large group of snails and slugs, marine, freshwater and land. Here it holds one family not placed in an order.',
  heterobranchia:     'Snails and slugs including sea slugs and land snails. Here it holds members not placed in an order, all fossils.',
  hygrophila:         'Freshwater air-breathing snails, e.g. pond snails, ramshorn snails and bladder snails; about half of the species here are fossils.',
  sorbeoconcha:       'Mostly marine snails with gills and a lid (operculum). Here it holds one family not placed in an order.',
  tectipleura:        'A large group of sea slugs, freshwater snails and land snails. Here it holds a fossil genus not placed lower.',
  vetigastropoda:     'An ancient line of sea snails, e.g. abalones, top shells and keyhole limpets. Here it holds members not placed in an order, almost all fossils.',
  palaeoloricata:     'Early chitons, all fossils. Here they are genera not placed in an order.',
  // Flatworms and sponges
  eucestoda:          'True tapeworms, gut parasites of vertebrates whose larvae carry six hooks. Here it holds old genera not placed in an order.',
  macrostomorpha:     'Small free-living flatworms of fresh water and the sea; Macrostomum is a lab model for regeneration.',
  digenea:            'Flukes with two suckers that pass through a snail before reaching their final host. Here it holds larval forms and old names not placed in an order.',
  heteroscleromorpha: 'Most demosponges, including freshwater sponges. Here it holds members not placed in an order, almost all fossils.',
  hexasterophora:     'Most glass sponges, with six-rayed silica spicules. Here it holds genera not placed in an order.',
  // Algae, plants and protozoa
  coscinodiscophycidae: 'Centric diatoms — round, radially symmetric diatoms of the plankton. Here it holds members not placed in an order, many of them fossils.',
  fragilariophycidae:   'Pennate diatoms without a raphe slit. Here it holds one genus not placed in an order.',
  corallinophycidae:    'Red algae that lay down lime in their cell walls, such as the coralline algae. Here it holds genera not placed in an order, mostly fossils.',
  pinidae:              'The conifers. Here it holds one genus not placed in an order, Austrosequoia.',
  metakinetoplastina:   'Most kinetoplastids, including bodonids and the trypanosomes. Here it holds one family not placed in an order.',
  prokinetoplastina:    'An early-branching group of kinetoplastid flagellates. Here it holds genera not placed in an order.',
  anisonemia:           'Flagellates related to the green euglenids, with two flagella, eating or absorbing food. Here it holds one genus not placed lower.',
};
