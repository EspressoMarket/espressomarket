exports.handler = async (event) => {
  const BEEHIIV_KEY = process.env.BEEHIIV_API_KEY;
  const BEEHIIV_PUB = process.env.BEEHIIV_PUBLICATION_ID;

  try {
    const response = await fetch(
      `https://api.beehiiv.com/v2/publications/${BEEHIIV_PUB}/subscriptions?status=active&limit=1`,
      {
        headers: {
          Authorization: `Bearer ${BEEHIIV_KEY}`
        }
      }
    );
    const data = await response.json();
    const total = data.total_results || 0;

    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: total })
    };
  } catch (e) {
    return {
      statusCode: 200,
      body: JSON.stringify({ count: 0 })
    };
  }
};
