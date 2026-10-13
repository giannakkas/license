import { DEFAULT_PRODUCT_SLUG } from "@/lib/catalog";
import { prisma } from "@/lib/db";
import { field, parseExpiry, parseSeats } from "@/lib/forms";
import { generateKey } from "@/lib/keys";
import { clientIp, done, readBody } from "@/lib/request";

export const runtime = "nodejs";

/**
 * Create a licence. Fields: productId, or product (the slug); customerId, or customerName to
 * create the customer on the spot (customerEmail optional); label (an optional reference),
 * maxSeats, expiresAt (YYYY-MM-DD), notes.
 */
export async function POST(request: Request) {
  const body = await readBody(request);
  const fail = (msg: string, status = 400) => done(request, `/?error=${encodeURIComponent(msg)}`, { error: msg }, status);

  const productId = field(body.productId, 64);
  const slug = field(body.product, 64) || (productId ? "" : DEFAULT_PRODUCT_SLUG);
  const product = productId
    ? await prisma.product.findUnique({ where: { id: productId } })
    : await prisma.product.findUnique({ where: { slug } });
  if (!product) return fail(productId ? "Choose a software" : `No software with the slug "${slug}". Add it under Software first.`);

  const customerId = field(body.customerId, 64);
  const customerName = field(body.customerName, 120);
  let customer = customerId ? await prisma.customer.findUnique({ where: { id: customerId } }) : null;
  if (!customer && customerName) {
    customer =
      (await prisma.customer.findFirst({ where: { name: { equals: customerName, mode: "insensitive" } } })) ??
      (await prisma.customer.create({ data: { name: customerName, email: field(body.customerEmail, 120) || null } }));
  }
  if (!customer) return fail("Choose a customer, or type the name of a new one");

  const seats = parseSeats(body.maxSeats);
  const expires = parseExpiry(body.expiresAt);
  if (!expires.ok) return fail("Invalid expiry date");
  const label = field(body.label, 120) || null;

  const license = await prisma.license.create({
    data: {
      key: generateKey(),
      productId: product.id,
      customerId: customer.id,
      label,
      maxSeats: seats,
      expiresAt: expires.date,
      notes: field(body.notes, 2000) || null,
    },
  });
  await prisma.event.create({
    data: {
      kind: "created",
      licenseId: license.id,
      detail: `${product.name} for ${customer.name}${label ? ` (${label})` : ""}, ${seats} seat(s)`,
      ip: clientIp(request),
    },
  });
  return done(request, `/licenses/${license.id}`, { ok: true, id: license.id, key: license.key, product: product.slug, customerId: customer.id }, 201);
}
