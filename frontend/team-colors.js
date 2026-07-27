(() => {
  const teams = [
    { name: "Ferrari", primary: "#DC0000", secondary: "#DC0000", aliases: ["scuderia ferrari"] },
    { name: "Mercedes", primary: "#C0C0C0", secondary: "#15151E", aliases: ["mercedes-amg", "mercedes amg"] },
    { name: "Red Bull Racing", primary: "#0A1B40", secondary: "#FFD700", aliases: ["red bull", "oracle red bull racing"] },
    { name: "McLaren", primary: "#FF8700", secondary: "#FF8700", aliases: ["mclaren formula 1 team"] },
    { name: "Aston Martin", primary: "#005F41", secondary: "#005F41", aliases: ["aston martin aramco"] },
    { name: "Alpine", primary: "#005BA9", secondary: "#FF80BD", aliases: ["alpine f1 team", "bwt alpine"] },
    { name: "Williams", primary: "#1868DB", secondary: "#1868DB", aliases: ["williams racing"] },
    { name: "Haas", primary: "#9C9FA2", secondary: "#9C9FA2", aliases: ["haas f1 team", "moneygram haas"] },
    { name: "Kick Sauber", primary: "#01C00E", secondary: "#01C00E", aliases: ["sauber", "stake f1 team kick sauber", "stake sauber"] },
    { name: "Audi", primary: "#C8CED4", secondary: "#F50537", aliases: ["audi f1 team", "audi revolut f1 team", "audi formula racing"] },
    { name: "Racing Bulls", primary: "#6C98FF", secondary: "#6C98FF", aliases: ["rb", "visa cash app rb", "vc arb", "vcarb", "rb f1 team"] },
  ];

  const fallback = "#6E7480";
  const normalize = (value) => String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

  function find(value) {
    const key = normalize(value);
    if (!key) return null;
    return teams.find((team) => {
      const names = [team.name, ...team.aliases].map(normalize);
      return names.some((name) => key === name || key.includes(name) || name.includes(key));
    }) || null;
  }

  function color(value, variant = "primary") {
    const team = find(value);
    return team?.[variant] || team?.primary || fallback;
  }

  function textColor(value) {
    const hex = color(value).slice(1);
    const [r, g, b] = [0, 2, 4].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16));
    return ((r * 299 + g * 587 + b * 114) / 1000) > 154 ? "#15151E" : "#FFFFFF";
  }

  window.F1Teams = { teams, find, color, textColor, fallback };
})();
