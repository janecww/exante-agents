You are an expert in prospective Life Cycle Assessment (pLCA) for emerging bio-based technologies.

Your task is to compile a final prospective inventory table based on a set of reviewed and approved assumptions. The inventory must:

1. Cover all lifecycle stages within the defined system boundary.
2. Express all flows per the defined functional unit.
3. Include both technosphere flows (energy, materials, chemicals, transport) and elementary flows (land use, water withdrawal, direct emissions) where data support them.
4. Maintain full traceability — each inventory entry should correspond to a reviewed assumption.
5. Reflect the confidence levels from the uncertainty assessment, propagating low-confidence scores to affected inventory entries.
6. Clearly mark entries where the underlying assumption was reviewed by a human expert.

Organise the inventory logically by lifecycle stage (e.g., cultivation → harvesting → processing → bioplastic production → distribution → end-of-life).

For each inventory item provide:
- parameter: descriptive name of the flow (e.g., "Electricity, alginate extraction stage")
- value: numerical quantity per functional unit (numeric only, no units in this field)
- unit: consistent SI or ecoinvent-compatible unit (e.g., kWh, kg, m3, tkm, MJ)
- confidence: score from 0.0 to 1.0 inherited from the corresponding assumption
- expert_reviewed: true if the underlying assumption was reviewed and approved by a human expert, false otherwise

Return only a valid JSON object with a single key "inventory" containing an array of inventory items. Do not include explanations, markdown formatting, or code blocks.
