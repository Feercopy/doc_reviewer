export type FeedbackUsefulness = "useful" | "partially_useful" | "useless";

export function usefulnessForFeedbackRating(rating: number): FeedbackUsefulness {
  if (rating <= 2) {
    return "useless";
  }
  if (rating === 3) {
    return "partially_useful";
  }
  return "useful";
}
