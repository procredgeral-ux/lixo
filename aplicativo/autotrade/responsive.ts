import { Dimensions } from 'react-native';

const { width, height } = Dimensions.get('window');

export const screenWidth = width;
export const screenHeight = height;

export const isSmallDevice = width < 360;
export const isLargeDevice = width >= 768;

const guidelineBaseWidth = 375;
const guidelineBaseHeight = 812;

export const scale = (size: number) => Math.round((width / guidelineBaseWidth) * size);
export const verticalScale = (size: number) => Math.round((height / guidelineBaseHeight) * size);
export const moderateScale = (size: number, factor = 0.5) =>
  Math.round(size + (scale(size) - size) * factor);

export const contentMaxWidth = Math.min(width - 48, 420);
export const contentMaxWidthWide = Math.min(width - 48, 520);
export const carouselMaxWidth = Math.min(width * 0.8, 300);
