"""Authored catalog: fictional tracks/artists (no licensed music). Acoustic values are hand-authored to be
realistic and internally consistent; clusters are tempo/key-linked so valid segue chains exist, including
half-time/double-time links between the lo-fi (≈86 BPM) and drum & bass (≈172 BPM) clusters.

Row: (id, title, artist, duration, bpm, key, energy, valence, cluster, [(ts, type, text), ...])
"""

TRACKS = [
    # ---- High-energy EDM, 124-128 BPM, around 8A ----
    ("t_2001", "Night Drive", "Nova Circuit", 214, 124, "8A", 0.78, 0.65, "edm", [
        (12, "sample_credit", "The vocal chop is sampled from a 1981 soul record the producer found in a Lisbon flea market."),
        (40, "artist_bio", "Nova Circuit is a two-person project from Rotterdam who met while repairing synthesizers."),
        (90, "trivia", "Produced during an all-night session in Berlin; the final mixdown happened at sunrise.")]),
    ("t_2002", "Glass Horizon", "Nova Circuit", 228, 126, "9A", 0.82, 0.6, "edm", [
        (8, "sample_credit", "The riser at the start is a reversed recording of a church organ in Utrecht."),
        (60, "trivia", "It was the closing track of Nova Circuit's first festival set."),
        (120, "glossary", "The 'pluck' lead is a short-decay synth note, a staple of progressive house.")]),
    ("t_2003", "Pulse Theory", "Kairo Vance", 205, 125, "8A", 0.86, 0.7, "edm", [
        (15, "artist_bio", "Kairo Vance taught music theory before going full-time as a producer."),
        (70, "sample_credit", "The clap layer comes from a field recording of a stadium crowd in Buenos Aires."),
        (130, "trivia", "The title refers to the producer's thesis on rhythm perception.")]),
    ("t_2004", "Afterglow Protocol", "Lumen Shift", 240, 128, "8B", 0.9, 0.78, "edm", [
        (20, "trivia", "Written in a single afternoon on a laptop during a delayed train journey."),
        (55, "artist_bio", "Lumen Shift is the alias of a former lighting designer for touring bands."),
        (110, "sample_credit", "The vocal hook is the artist's sister humming, pitched up seven semitones.")]),
    ("t_2005", "Signal Bloom", "Kairo Vance", 219, 123, "7A", 0.74, 0.55, "edm", [
        (10, "sample_credit", "The pad is built from a slowed-down recording of wind chimes."),
        (75, "trivia", "It almost didn't get released — the stems were recovered from a broken hard drive."),
        (140, "artist_bio", "Kairo Vance releases one track per full moon as a personal challenge.")]),
    ("t_2006", "Overdrive Hearts", "Lumen Shift", 232, 127, "9B", 0.88, 0.82, "edm", [
        (18, "sample_credit", "The guitar stab is lifted from a 1970s Italian library-music record."),
        (66, "trivia", "Its working title was 'Untitled 44' for nearly two years.")]),
    # ---- Deep / soulful house, 118-122 BPM, around 4A-5A ----
    ("t_3001", "Velvet Hours", "Mara Okafor", 260, 120, "5A", 0.62, 0.58, "house", [
        (14, "artist_bio", "Mara Okafor DJ'd a weekly basement night in Lagos for six years before producing."),
        (52, "sample_credit", "The piano chords are replayed from a gospel recording from a 1970s choir album."),
        (130, "trivia", "Recorded with a single microphone in the artist's kitchen.")]),
    ("t_3002", "Low Sun", "Mara Okafor", 248, 121, "4A", 0.58, 0.52, "house", [
        (22, "sample_credit", "The shaker loop is the artist tapping a box of matches."),
        (95, "trivia", "It was written as a warm-up track and became the most-requested one.")]),
    ("t_3003", "Concrete Garden", "Theo Lindqvist", 236, 122, "5B", 0.66, 0.68, "house", [
        (16, "artist_bio", "Theo Lindqvist is a Swedish architect who produces house music between projects."),
        (60, "trivia", "The title comes from a rooftop garden the artist designed in Malmö."),
        (150, "glossary", "A 'four-on-the-floor' beat puts the kick drum on every quarter note.")]),
    ("t_3004", "Slow Motion City", "Theo Lindqvist", 252, 119, "6A", 0.6, 0.5, "house", [
        (30, "sample_credit", "The vocal phrase is from a public-domain 1950s radio broadcast about city planning."),
        (110, "trivia", "Mixed entirely on headphones on a night ferry.")]),
    ("t_3005", "Brass Lantern", "Ines Calderón", 244, 118, "4B", 0.64, 0.72, "house", [
        (12, "sample_credit", "The horn riff was recorded by a street band the artist met in Valencia."),
        (80, "artist_bio", "Ines Calderón started as a trumpet player in a jazz trio."),
        (160, "trivia", "The final version uses the street band's third take, mistakes included.")]),
    # ---- Disco / nu-funk, 110-116 BPM, around 11B ----
    ("t_4001", "Mirrorball Mondays", "The Sundial Club", 222, 114, "11B", 0.72, 0.88, "disco", [
        (10, "artist_bio", "The Sundial Club is a six-piece band that only plays on Mondays."),
        (45, "sample_credit", "The string swell is from the band's own rehearsal tape, played backwards."),
        (100, "trivia", "The bassline was written on a toy keyboard.")]),
    ("t_4002", "Satin Getaway", "The Sundial Club", 236, 116, "12B", 0.7, 0.84, "disco", [
        (25, "trivia", "The handclaps were recorded by everyone at the album release party."),
        (90, "glossary", "Nu-disco updates 1970s disco grooves with modern synths and production.")]),
    ("t_4003", "Roller Rink Royalty", "Dex Amari", 210, 112, "11A", 0.68, 0.8, "disco", [
        (8, "artist_bio", "Dex Amari worked as a roller-rink DJ through college."),
        (60, "sample_credit", "The talkbox vocal was performed through a modified garden hose."),
        (120, "trivia", "The track was premiered at an actual roller rink in Detroit.")]),
    ("t_4004", "Gold Leaf Groove", "Dex Amari", 228, 115, "10B", 0.74, 0.86, "disco", [
        (18, "sample_credit", "The rhythm guitar is a re-played interpolation, not a direct sample."),
        (70, "trivia", "Dex Amari recorded the guitar part in one take after a power cut.")]),
    ("t_4005", "Neon Sunday", "Ines Calderón", 218, 117, "12A", 0.66, 0.74, "disco", [
        (20, "trivia", "Written for a friend's wedding and released at their request."),
        (95, "sample_credit", "The crowd noise is from the wedding itself.")]),
    # ---- Lo-fi / chillhop, 82-90 BPM, around 2A ----
    ("t_5001", "Paper Moons", "Hazel & the Static", 186, 86, "2A", 0.32, 0.45, "lofi", [
        (6, "sample_credit", "The vinyl crackle is real — sampled from the artist's grandmother's record player."),
        (50, "artist_bio", "Hazel & the Static is a bedroom project started during a long winter in Halifax."),
        (110, "trivia", "The melody was hummed into a voice memo at 3am.")]),
    ("t_5002", "Rainy Tram", "Hazel & the Static", 174, 84, "3A", 0.28, 0.4, "lofi", [
        (14, "sample_credit", "The rain sound was recorded on a tram roof in Lisbon."),
        (80, "trivia", "It is in 3A, one step round the Camelot wheel from 'Paper Moons'.")]),
    ("t_5003", "Study Lamp", "Kenji Morrow", 192, 88, "2B", 0.35, 0.6, "lofi", [
        (10, "artist_bio", "Kenji Morrow makes beats between night shifts as a hospital pharmacist."),
        (70, "sample_credit", "The Rhodes chords are played live, then bit-crushed."),
        (130, "glossary", "Bit-crushing reduces audio resolution to create a gritty, retro texture.")]),
    ("t_5004", "Cardigan Weather", "Kenji Morrow", 180, 82, "1A", 0.25, 0.42, "lofi", [
        (22, "trivia", "The title won a naming poll among the artist's livestream viewers."),
        (90, "sample_credit", "The guitar loop is the artist's first ever recorded riff from age fourteen.")]),
    ("t_5005", "Window Seat", "Hazel & the Static", 198, 90, "2A", 0.38, 0.5, "lofi", [
        (12, "trivia", "Composed on a 14-hour bus ride with a pocket synth."),
        (100, "sample_credit", "The announcement chime is from the actual bus.")]),
    # ---- Liquid drum & bass, 170-176 BPM, around 2A ----
    ("t_6001", "Tidal Memory", "Rowan Each", 246, 172, "2A", 0.84, 0.55, "dnb", [
        (16, "artist_bio", "Rowan Each is a former marine biologist turned drum & bass producer."),
        (64, "sample_credit", "The breakbeat is chopped from a free-to-use drum session recorded in 2019."),
        (140, "trivia", "It sits at exactly double the tempo of 'Paper Moons', so the two mix in half-time.")]),
    ("t_6002", "Coastline Static", "Rowan Each", 238, 174, "3A", 0.88, 0.5, "dnb", [
        (20, "sample_credit", "The seagull calls were recorded at a Cornish harbour."),
        (100, "glossary", "Liquid drum & bass pairs fast breakbeats with smooth, melodic pads.")]),
    ("t_6003", "Northern Relay", "Saoirse Venn", 226, 170, "1A", 0.82, 0.48, "dnb", [
        (10, "artist_bio", "Saoirse Venn performs live with a drum pad and a cello."),
        (80, "trivia", "The cello was recorded in a disused railway tunnel for the reverb.")]),
    ("t_6004", "Afterhours Arc", "Saoirse Venn", 252, 176, "2B", 0.9, 0.62, "dnb", [
        (14, "sample_credit", "The vocal is the artist reading a poem, time-stretched by 300%."),
        (120, "trivia", "It was the first track mastered at the artist's new studio.")]),
]

USERS = [  # (email, display name, role). Demo password comes from SEED_PASSWORD.
    ("admin@djstudio.dev", "Ada Admin", "admin"),
    ("host@djstudio.dev", "Harper Host", "host"),
    ("codj@djstudio.dev", "Cole CoDJ", "co_dj"),
    ("listener@djstudio.dev", "Lee Listener", "listener"),
    ("guest@djstudio.dev", "Gia Guest", "listener"),
]
